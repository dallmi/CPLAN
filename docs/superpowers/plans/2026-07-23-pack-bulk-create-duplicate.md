# Pack Bulk Creation & Activity Duplicate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create all activities of a communication pack in one pass (shared fields + channel matrix, atomic batch API), duplicate any activity from table or drawer, and filter the Activities table by campaign/pack.

**Architecture:** The existing activity drawer gains a third mode ("pack") that hides the per-activity fields (name, channel, start, end) and shows a channel checkbox matrix plus one row per checked channel. Submission posts to a new atomic `POST /api/activities/batch` endpoint that generates sequential tracking IDs in one transaction. Duplicate reuses the existing create-mode drawer, prefilled via `populateDrawerForm`. Spec: `docs/superpowers/specs/2026-07-23-pack-bulk-create-duplicate-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy (`pipeline/api/app.py`), vanilla JS studio (`pipeline/studio/`), pytest + unittest DOM-contract tests.

## Global Constraints

- Corporate design system only: existing CSS vars (`--surface`, `--grey-*`, `--row-alt`, …), border-radius 2px, Lucide inline SVG icons, no emojis (guarded by `test_no_emoji_codepoints`).
- Batch size 1–50 items; all-or-nothing persistence.
- Tracking IDs are server-generated only; sequential activity numbers within a batch.
- Cluster scope excluded — pack level only.
- Existing single-create endpoint unchanged.
- All UI copy in English.
- Commit and push after every task.

---

### Task 1: Atomic batch-create endpoint

**Files:**
- Modify: `pipeline/api/app.py` (add `ActivityBatchCreate` after `ActivityList` ~line 396; add endpoint after `create_activity` ~line 587)
- Test: `tests/test_api.py` (append after `test_create_retries_on_tracking_id_collision_from_a_concurrent_insert`)

**Interfaces:**
- Consumes: existing `ActivityCreate`, `ActivityList`, `generate_tracking_id`, `_increment_activity_number`, `MAX_TRACKING_ID_GENERATION_ATTEMPTS`, `MAX_TRACKING_ID_COMMIT_RETRIES`, `Activity`, `ActivityChange`.
- Produces: `POST /api/activities/batch` accepting `{"items": [ActivityCreate, ...]}` (1–50), returning `{"items": [ActivityRead, ...], "total": N}` with HTTP 201. Task 2's frontend calls exactly this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_batch_create_creates_all_activities_with_sequential_tracking_ids(client):
    response = client.post(
        "/api/activities/batch",
        json={
            "items": [
                {
                    "source_type": "internal",
                    "activity_name": f"Q2 results — {channel}",
                    "communication_pack_cpid": "QRREP-0000058",
                    "channel": channel,
                    "start_date": "2026-08-12T09:00:00+02:00",
                    "end_date": "2026-08-12T10:00:00+02:00",
                }
                for channel in ("Email", "Intranet", "Townhall")
            ]
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    numbers = [int(item["tracking_id"].split("-")[3]) for item in body["items"]]
    assert numbers == [numbers[0], numbers[0] + 1, numbers[0] + 2]
    for item in body["items"]:
        assert item["tracking_id"].startswith("QRREP-0000058-")
        assert TRACKING_ID_PATTERN.match(item["tracking_id"])
    # Request order is preserved.
    assert [item["channel"] for item in body["items"]] == ["Email", "Intranet", "Townhall"]


def test_batch_create_is_atomic_when_one_item_is_invalid(client):
    response = client.post(
        "/api/activities/batch",
        json={
            "items": [
                {
                    "source_type": "internal",
                    "activity_name": "Valid item",
                    "start_date": "2026-08-12T09:00:00+02:00",
                    "end_date": "2026-08-12T10:00:00+02:00",
                },
                {
                    "source_type": "internal",
                    "activity_name": "Invalid item",
                    "start_date": "2026-08-12T10:00:00+02:00",
                    "end_date": "2026-08-12T09:00:00+02:00",
                },
            ]
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    # The failing item's index is addressable for the frontend row mapping.
    assert any(entry["loc"][:3] == ["body", "items", 1] for entry in detail)
    assert client.get("/api/activities").json()["total"] == 0


def test_batch_create_rejects_empty_and_oversized_batches(client):
    assert client.post("/api/activities/batch", json={"items": []}).status_code == 422
    item = {
        "source_type": "internal",
        "activity_name": "Limit probe",
        "start_date": "2026-08-12T09:00:00+02:00",
        "end_date": "2026-08-12T10:00:00+02:00",
    }
    assert client.post("/api/activities/batch", json={"items": [item] * 51}).status_code == 422
    assert client.get("/api/activities").json()["total"] == 0


def test_batch_create_writes_one_created_change_row_per_activity(client):
    response = client.post(
        "/api/activities/batch",
        json={
            "items": [
                {
                    "source_type": "internal",
                    "activity_name": f"History probe {index}",
                    "start_date": "2026-08-12T09:00:00+02:00",
                    "end_date": "2026-08-12T10:00:00+02:00",
                }
                for index in range(2)
            ]
        },
    )
    assert response.status_code == 201, response.text
    for item in response.json()["items"]:
        changes = client.get(f"/api/activities/{item['id']}/changes").json()
        assert changes["total"] == 1
        assert changes["items"][0]["change_type"] == "created"
        assert changes["items"][0]["actor"] == "studio"
        assert changes["items"][0]["version_to"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_api.py -k batch_create -v`
Expected: 4 FAILs — `404 Not Found` (route does not exist; note: a 404 also fails the 422 assertions).

- [ ] **Step 3: Implement model and endpoint**

In `pipeline/api/app.py`, after `class ActivityList` (~line 396):

```python
class ActivityBatchCreate(BaseModel):
    items: list[ActivityCreate] = Field(min_length=1, max_length=50)
```

Inside `create_app`, directly after the `create_activity` route function (~line 587):

```python
    @app.post("/api/activities/batch", response_model=ActivityList, status_code=status.HTTP_201_CREATED)
    def create_activities_batch(payload: ActivityBatchCreate):
        """Create a communication pack's activities in one atomic transaction.

        Tracking IDs are generated sequentially inside the batch: each
        generated (channel, tracking_id) pair is appended to `existing`
        before the next item is processed, so activity numbers within the
        pack are consecutive and cannot collide with each other.
        """
        with Session(engine) as session:
            commit_attempts = 0
            while True:
                existing = [
                    (channel, tracking_id)
                    for channel, tracking_id in session.execute(
                        select(Activity.channel, Activity.tracking_id).where(Activity.tracking_id.isnot(None))
                    ).all()
                ]
                created: list[Activity] = []
                for item in payload.items:
                    tracking_id = generate_tracking_id(
                        existing,
                        communication_pack_cpid=item.communication_pack_cpid,
                        start_date=item.start_date,
                        channel=item.channel,
                    )
                    taken = {existing_tracking_id for _, existing_tracking_id in existing}
                    generation_attempts = 0
                    while (
                        tracking_id in taken
                        or session.scalar(select(Activity.id).where(Activity.tracking_id == tracking_id))
                        is not None
                    ):
                        generation_attempts += 1
                        if generation_attempts > MAX_TRACKING_ID_GENERATION_ATTEMPTS:
                            raise HTTPException(
                                status_code=500, detail={"code": "tracking_id_generation_exhausted"}
                            )
                        tracking_id = _increment_activity_number(tracking_id)
                    existing.append((item.channel, tracking_id))
                    activity_id = uuid.uuid4()
                    activity = Activity(id=activity_id, **item.model_dump(), tracking_id=tracking_id)
                    session.add(activity)
                    session.add(
                        ActivityChange(
                            activity_id=activity_id,
                            actor="studio",
                            change_type="created",
                            version_to=1,
                        )
                    )
                    created.append(activity)
                try:
                    session.commit()
                except IntegrityError:
                    # Concurrency backstop mirroring create_activity: a
                    # concurrent request committed one of our tracking_ids
                    # after the fast-path SELECT passed. All-or-nothing:
                    # roll back the whole batch and regenerate every ID.
                    session.rollback()
                    commit_attempts += 1
                    if commit_attempts > MAX_TRACKING_ID_COMMIT_RETRIES:
                        raise HTTPException(
                            status_code=500, detail={"code": "tracking_id_generation_exhausted"}
                        )
                    continue
                for activity in created:
                    session.refresh(activity)
                return {"items": created, "total": len(created)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_api.py -k batch_create -v`
Expected: 4 PASS (8 with the postgres param if `CPLAN_TEST_DATABASE_URL` is set).

- [ ] **Step 5: Run the full API suite for regressions**

Run: `python3 -m pytest tests/test_api.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pipeline/api/app.py tests/test_api.py
git commit -m "Add atomic POST /api/activities/batch with sequential tracking IDs"
git push
```

---

### Task 2: Pack drawer mode in the studio

**Files:**
- Modify: `pipeline/studio/index.html` (page-actions ~line 100, drawer form ~lines 152–232)
- Modify: `pipeline/studio/app.js`
- Modify: `pipeline/studio/styles.css` (append)
- Modify: `pipeline/studio/README.md` (capabilities list)
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes: `POST /api/activities/batch` from Task 1 (`{items:[...]}` → `{items, total}`).
- Produces: `repository.createActivitiesBatch(items)`, `state.packing`, `setPackMode(on)`, `openPackDrawer(opener)`, `async function submitPack(event)`, `[data-single-only]` markup convention. Task 3 reuses `setPackMode(false)` in the duplicate flow.

- [ ] **Step 1: Write the failing DOM-contract test**

Append to `tests/test_studio.py` inside `StudioTests` (before `test_inline_svg_favicon_no_network`):

```python
    def test_pack_drawer_markup_and_batch_flow(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="pack-new"', html)
        self.assertIn(">New pack<", html)
        self.assertIn('id="pack-section"', html)
        self.assertIn('id="pack-channels"', html)
        self.assertIn('id="pack-rows"', html)
        self.assertIn('id="pack-channel-new"', html)
        self.assertIn('id="pack-channel-add"', html)
        # Per-activity fields are hidden in pack mode via this marker.
        self.assertIn("data-single-only", html)
        self.assertIn("/api/activities/batch", app)
        self.assertIn("createActivitiesBatch", app)
        self.assertIn("async function submitPack(", app)
        self.assertIn("function openPackDrawer(", app)
        self.assertIn("function setPackMode(", app)
        self.assertIn("state.packing", app)
        self.assertIn("activities created", app)
        # Batch API item indices are translated to channel-row names.
        self.assertIn("function packErrorMessage(", app)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_studio.py -k pack_drawer -v`
Expected: FAIL on `id="pack-new"`.

- [ ] **Step 3: Add markup to index.html**

Replace the page-actions div (line 100):

```html
<div class="page-actions"><button class="btn primary" id="pack-new">New pack</button><button class="btn secondary" id="activity-new">New activity</button><button class="btn secondary" id="activity-export">Export filtered CSV</button></div>
```

Inside `#activity-form`, directly after the closing `</div>` of `#form-variant` (line 159), insert:

```html
        <div id="pack-section" hidden>
          <fieldset><legend>Channels</legend>
            <div class="channel-matrix" id="pack-channels"></div>
            <div class="pack-add-channel">
              <input id="pack-channel-new" placeholder="Add another channel" aria-label="Add another channel">
              <button type="button" class="btn secondary" id="pack-channel-add">Add</button>
            </div>
          </fieldset>
          <fieldset><legend>Activities</legend>
            <div id="pack-rows"></div>
          </fieldset>
        </div>
```

Mark the three per-activity blocks with `data-single-only`:
- Identity fieldset: `<label data-single-only>Activity name <span class="req">*</span><input name="activity_name" maxlength="500"></label>`
- Classification fieldset: `<label data-single-only>Channel <span class="req">*</span><select name="channel">…</select></label>`
- Schedule fieldset: `<div class="form-grid" data-single-only><label>Start date (local time) …</label><label>End date (local time) …</label></div>`

(Time zone stays visible — it is shared across the pack.)

- [ ] **Step 4: Add repository method, state, and pack functions to app.js**

State (line 6): add `packing:false, customChannels:[]` to the `state` object literal.

In `DatabasePlanningRepository`, after `createActivity`:

```js
    createActivitiesBatch(items) {
      return this.request('/api/activities/batch', {method:'POST',body:JSON.stringify({items})});
    }
```

After `openCreateDrawer` add:

```js
  const PACK_ROW_FIELDS=['activity_name','channel','start_date','end_date'];

  function setPackMode(on) {
    document.getElementById('pack-section').hidden=!on;
    document.querySelectorAll('#activity-form [data-single-only]').forEach(el=>{el.hidden=on;});
  }

  function packSelectedChannels() {
    return Array.from(document.querySelectorAll('#pack-channels input:checked')).map(input=>input.value);
  }

  function renderPackChannels(sourceType) {
    const all=distinctChannels(sourceType).slice();
    state.customChannels.forEach(channel=>{if(!all.includes(channel))all.push(channel);});
    const selected=packSelectedChannels();
    document.getElementById('pack-channels').innerHTML=all.length
      ?all.map(channel=>`<label class="ms-option"><input type="checkbox" value="${esc(channel)}"${selected.includes(channel)?' checked':''}><span>${esc(channel)}</span></label>`).join('')
      :'<div class="ms-empty">No channels in the data yet — add one below</div>';
  }

  function packRowValues() {
    return Array.from(document.querySelectorAll('#pack-rows .pack-row')).map(rowEl=>({
      channel:rowEl.dataset.channel,
      name:rowEl.querySelector('[data-pack-name]').value,
      start:rowEl.querySelector('[data-pack-start]').value,
      end:rowEl.querySelector('[data-pack-end]').value,
    }));
  }

  function renderPackRows() {
    const previousRows=packRowValues();
    const previous=new Map(previousRows.map(row=>[row.channel,row]));
    const first=previousRows[0];
    const campaign=String(form().elements.campaign.value||'').trim();
    document.getElementById('pack-rows').innerHTML=packSelectedChannels().map(channel=>{
      const prev=previous.get(channel);
      const name=prev?prev.name:(campaign?`${campaign} — ${channel}`:channel);
      const start=prev?prev.start:(first?first.start:'');
      const end=prev?prev.end:(first?first.end:'');
      return `<div class="pack-row" data-channel="${esc(channel)}"><div class="pack-row-channel">${esc(channel)}</div><label>Activity name <span class="req">*</span><input data-pack-name value="${esc(name)}"></label><div class="form-grid"><label>Start date (local time) <span class="req">*</span><input type="datetime-local" data-pack-start value="${esc(start)}"></label><label>End date (local time) <span class="req">*</span><input type="datetime-local" data-pack-end value="${esc(end)}"></label></div></div>`;
    }).join('')||'<div class="ms-empty">Select at least one channel above</div>';
    updatePackSubmitLabel();
  }

  function updatePackSubmitLabel() {
    if(!state.packing)return;
    const count=packSelectedChannels().length;
    document.getElementById('drawer-save').textContent=count?`Create ${count} ${count===1?'activity':'activities'}`:'Create activities';
  }

  function openPackDrawer(opener) {
    state.selected=null;state.creating=false;state.packing=true;state.editing=true;state.dirty=false;state.customChannels=[];state.drawerOpener=opener||document.activeElement;
    document.getElementById('drawer-title').textContent='New pack';
    document.getElementById('drawer-tracking').textContent='Tracking IDs are generated on save';
    document.getElementById('drawer-mode-label').textContent='New pack';
    document.getElementById('drawer-mode-label').className='badge info';
    document.getElementById('drawer-edit').style.display='none';
    document.querySelector('.drawer-actions').style.display='flex';
    document.getElementById('form-validation').textContent='';
    document.getElementById('form-variant').hidden=false;
    document.getElementById('drawer-history').hidden=true;
    setSourceToggle('internal');
    resetCreateForm();
    applyVariant('internal');
    populateSelectOptions('internal');
    renderMultiselectOptions();
    setFormEnabled(true);
    setPackMode(true);
    renderPackChannels('internal');
    renderPackRows();
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    form().elements.campaign.focus();
  }

  function packErrorMessage(message, rows) {
    // Translate pydantic loc paths ("items.1.end_date: ...") into the
    // channel-row language the user sees ("Intranet End date: ...").
    return String(message).replace(/items\.(\d+)\.?([a-z_]*)/g,(match,index,field)=>{
      const row=rows[Number(index)];
      if(!row)return match;
      const label=field?(FIELD_LABELS[field]||field):'';
      return label?`${row.channel} ${label}`:row.channel;
    });
  }

  async function submitPack(event) {
    event.preventDefault();
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const value=name=>{const el=form().elements[name];return el?String(el.value||'').trim():'';};
    const required=(sourceType==='internal'?REQUIRED_INTERNAL:REQUIRED_EXTERNAL).filter(name=>!PACK_ROW_FIELDS.includes(name));
    const missing=required.filter(name=>!value(name));
    if(missing.length){
      validation.textContent=`Complete the required fields: ${missing.map(name=>FIELD_LABELS[name]||name).join(', ')}.`;
      focusField(missing[0]);
      return;
    }
    const rows=packRowValues();
    if(!rows.length){validation.textContent='Select at least one channel.';return;}
    for(const row of rows){
      if(!row.name.trim()){validation.textContent=`${row.channel}: activity name is required.`;return;}
      if(!row.start||!row.end){validation.textContent=`${row.channel}: start and end date are required.`;return;}
      const start=A.parseDate(row.start),end=A.parseDate(row.end);
      if(start&&end&&end<start){validation.textContent=`${row.channel}: end date cannot be before start date.`;return;}
    }
    const shared={source_type:sourceType};
    CREATE_FIELDS.forEach(name=>{
      if(PACK_ROW_FIELDS.includes(name))return;
      if(name==='audience'&&sourceType!=='internal')return;
      const raw=value(name);
      if(raw)shared[name]=raw;
    });
    if(sourceType==='internal')shared.news_digest=form().elements.news_digest.checked;
    const items=rows.map(row=>Object.assign({},shared,{
      activity_name:row.name.trim(),
      channel:row.channel,
      start_date:new Date(row.start).toISOString(),
      end_date:new Date(row.end).toISOString(),
    }));
    validation.textContent='';
    try {
      const created=await repository.createActivitiesBatch(items);
      created.items.forEach(item=>state.snapshotRows.push(item));
      state.packing=false;state.dirty=false;
      toast(`${created.items.length} activities created`);
      closeDrawer();
      renderAll();
    } catch(error) {
      validation.textContent=packErrorMessage(error.message,rows);
    }
  }
```

- [ ] **Step 5: Wire pack mode into the existing flows in app.js**

1. `closeDrawer` (line 594): add `state.packing=false;setPackMode(false);` before restoring focus (extend the existing reset statement).
2. `openDrawer` (line 554): add `state.packing=false;` to the state reset line and call `setPackMode(false);` before `setDrawerEditing(false);`.
3. `openCreateDrawer` (line 571): add `state.packing=false;` to the state reset line and call `setPackMode(false);` after `resetCreateForm();`.
4. Form submit routing (line 769): `activityForm.onsubmit=event=>state.packing?submitPack(event):state.creating?submitCreate(event):saveDraft(event);`
5. `wireEvents`: after the `activity-new` wiring add:

```js
    document.getElementById('pack-new').onclick=event=>openPackDrawer(event.currentTarget);
    document.getElementById('pack-channels').addEventListener('change',()=>{renderPackRows();state.dirty=true;});
    document.getElementById('pack-rows').addEventListener('input',updatePackSubmitLabel);
    document.getElementById('pack-channel-add').onclick=()=>{
      const input=document.getElementById('pack-channel-new');
      const channel=String(input.value||'').trim();
      if(!channel)return;
      if(!state.customChannels.includes(channel))state.customChannels.push(channel);
      renderPackChannels(currentSourceType());
      const box=Array.from(document.querySelectorAll('#pack-channels input')).find(item=>item.value===channel);
      if(box)box.checked=true;
      input.value='';
      renderPackRows();
      state.dirty=true;
    };
```

6. `source-toggle` handler (line 754): after `renderMultiselectOptions();` add `if(state.packing){renderPackChannels(source);renderPackRows();}`.
7. `drawer-cancel` handler (line 762): change the create-mode early exit to `if(state.creating||state.packing){closeDrawer();return;}`.

- [ ] **Step 6: Append CSS to styles.css**

```css
.channel-matrix{display:grid;grid-template-columns:repeat(2,1fr);gap:2px 10px;margin-bottom:10px}
.pack-add-channel{display:flex;gap:8px;align-items:center}
.pack-add-channel input{flex:1;margin-top:0}
.pack-add-channel .btn{flex:none}
.pack-row{border:1px solid var(--surface);border-left:3px solid var(--grey-1);padding:12px;margin-bottom:10px;background:var(--row-alt)}
.pack-row-channel{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
```

- [ ] **Step 7: Update the studio README capabilities list**

In `pipeline/studio/README.md`, add to "Included planning capabilities":

```markdown
- Pack bulk creation: shared fields once, channel matrix, one atomic batch save
```

- [ ] **Step 8: Run tests**

Run: `python3 -m pytest tests/test_studio.py -v && node --check pipeline/studio/app.js`
Expected: all PASS, no syntax errors.

- [ ] **Step 9: Commit**

```bash
git add pipeline/studio/index.html pipeline/studio/app.js pipeline/studio/styles.css pipeline/studio/README.md tests/test_studio.py
git commit -m "Add pack drawer mode with channel matrix and atomic batch save"
git push
```

---

### Task 3: Duplicate from table row and drawer

**Files:**
- Modify: `pipeline/studio/index.html` (drawer-mode div line 151, activities table line 110)
- Modify: `pipeline/studio/app.js`
- Modify: `pipeline/studio/styles.css` (append)
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes: `setPackMode(false)` from Task 2, existing `populateDrawerForm`, `submitCreate` (create path is reused unchanged — `state.creating=true`).
- Produces: `openDuplicateDrawer(row, opener)`, `#drawer-duplicate` button, `[data-duplicate-id]` row buttons.

- [ ] **Step 1: Write the failing DOM-contract test**

Append to `tests/test_studio.py`:

```python
    def test_duplicate_entry_points(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="drawer-duplicate"', html)
        self.assertIn(">Duplicate<", html)
        self.assertIn("function openDuplicateDrawer(", app)
        self.assertIn("data-duplicate-id", app)
        self.assertIn("Duplicate of ", app)
        # Row button must not bubble into the row's open-drawer handler.
        self.assertIn("stopPropagation", app)
        # Name is focused and pre-selected for quick overwrite.
        self.assertIn("nameEl.select()", app)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_studio.py -k duplicate_entry -v`
Expected: FAIL on `id="drawer-duplicate"`.

- [ ] **Step 3: Add markup**

`index.html` line 151 — extend the drawer-mode div:

```html
<div class="drawer-mode"><span class="badge neutral" id="drawer-mode-label">Read only</span><div class="drawer-mode-actions"><button class="btn secondary" id="drawer-duplicate">Duplicate</button><button class="btn primary" id="drawer-edit">Edit activity</button></div></div>
```

`index.html` line 110 — add a trailing header cell to the activities table:

```html
<th class="action-cell" aria-label="Row actions"></th>
```

- [ ] **Step 4: Implement in app.js**

After `openPackDrawer` add:

```js
  function openDuplicateDrawer(row, opener) {
    const sourceType=row.source_type||'internal';
    state.selected=null;state.creating=true;state.packing=false;state.editing=true;state.dirty=false;state.drawerOpener=opener||document.activeElement;
    document.getElementById('drawer-title').textContent=`Duplicate of ${row.activity_name||'Untitled activity'}`;
    document.getElementById('drawer-tracking').textContent='Tracking ID is generated on save';
    document.getElementById('drawer-mode-label').textContent='New record';
    document.getElementById('drawer-mode-label').className='badge info';
    document.getElementById('drawer-edit').style.display='none';
    document.getElementById('drawer-duplicate').style.display='none';
    document.querySelector('.drawer-actions').style.display='flex';
    document.getElementById('drawer-save').textContent='Create activity';
    document.getElementById('form-validation').textContent='';
    document.getElementById('form-variant').hidden=false;
    document.getElementById('drawer-history').hidden=true;
    setPackMode(false);
    setSourceToggle(sourceType);
    resetCreateForm();
    applyVariant(sourceType);
    populateSelectOptions(sourceType);
    populateDrawerForm(row);
    renderMultiselectOptions();
    setFormEnabled(true);
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    const nameEl=form().elements.activity_name;
    nameEl.focus();nameEl.select();
  }
```

In `applyActivityFilters` (line 264), add the action cell to the row template before `</tr>` (Lucide `copy` icon, inline SVG):

```js
<td class="action-cell"><button type="button" class="icon-btn duplicate-btn" data-duplicate-id="${esc(row.id||'')}" aria-label="Duplicate ${esc(row.activity_name||'activity')}" title="Duplicate"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button></td>
```

and change the empty-state colspan from `8` to `9`.

Add a binder after `bindOpenRows`:

```js
  function bindDuplicateButtons() {
    document.querySelectorAll('[data-duplicate-id]').forEach(btn=>{
      btn.onclick=event=>{
        event.stopPropagation();
        const row=state.rows.find(item=>String(item.id)===String(btn.dataset.duplicateId));
        if(row)openDuplicateDrawer(row,btn);
      };
      // Enter/Space on the button must not bubble into the row's open handler.
      btn.onkeydown=event=>event.stopPropagation();
    });
  }
```

Call `bindDuplicateButtons();` in `renderAll` (after `bindOpenRows();`) and in `runActivityFilters` (`const runActivityFilters=()=>{applyActivityFilters();bindOpenRows();bindDuplicateButtons();};`).

Visibility wiring:
1. `setDrawerEditing` (line 650): next to the `drawer-edit` display line add `document.getElementById('drawer-duplicate').style.display=editing?'none':'inline-block';`
2. `openCreateDrawer` and `openPackDrawer`: add `document.getElementById('drawer-duplicate').style.display='none';` next to the existing `drawer-edit` hide.
3. `wireEvents`: `document.getElementById('drawer-duplicate').onclick=()=>{if(state.selected)openDuplicateDrawer(state.selected,state.drawerOpener);};`

- [ ] **Step 5: Append CSS to styles.css**

```css
.drawer-mode-actions{display:flex;gap:8px}
.action-cell{width:34px;text-align:center}
td.action-cell{overflow:visible}
.duplicate-btn{width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;color:var(--grey-4)}
.duplicate-btn:hover{color:var(--black);background:var(--surface)}
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_studio.py -v && node --check pipeline/studio/app.js`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline/studio/index.html pipeline/studio/app.js pipeline/studio/styles.css tests/test_studio.py
git commit -m "Add activity duplicate from table rows and the detail drawer"
git push
```

---

### Task 4: Campaign/pack filter in the Activities filterbar

**Files:**
- Modify: `pipeline/studio/index.html` (filterbar ~line 101)
- Modify: `pipeline/studio/app.js` (`populateActivityFilters`, `applyActivityFilters`, `wireEvents`)
- Modify: `pipeline/studio/README.md` (capabilities list)
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes: existing `campaignLabel(row)` helper (returns campaign, else pack CPID, else tracking pack prefix; standalone prefix filtered out).
- Produces: `#activity-campaign` select participating in filter/clear/change wiring.

- [ ] **Step 1: Write the failing DOM-contract test**

Append to `tests/test_studio.py`:

```python
    def test_campaign_pack_filter(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="activity-campaign"', html)
        self.assertIn("All campaigns / packs", html)
        # Wired into populate, apply, clear, and change-listener paths.
        self.assertIn("'activity-campaign'", app)
        self.assertIn("campaignLabel(row)===campaign", app.replace(" ", ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_studio.py -k campaign_pack_filter -v`
Expected: FAIL on `id="activity-campaign"`.

- [ ] **Step 3: Implement**

`index.html` — in the filterbar after `#activity-priority`:

```html
<select id="activity-campaign"><option value="">All campaigns / packs</option></select>
```

`app.js` — `populateActivityFilters` (line 250), add:

```js
    const campaigns=new Set();
    state.rows.forEach(row=>{const label=campaignLabel(row);if(label)campaigns.add(label);});
    fill('activity-campaign',Array.from(campaigns).sort((a,b)=>a.localeCompare(b)),'campaigns / packs');
```

`applyActivityFilters` (line 257): read `campaign=document.getElementById('activity-campaign').value` alongside the other filters and extend the row predicate with `&&(!campaign||campaignLabel(row)===campaign)`.

`wireEvents`: add `'activity-campaign'` to both the change-listener id array (line 749) and the clear-button id array (line 750).

`pipeline/studio/README.md` — extend the capabilities bullet list:

```markdown
- Activity duplication and campaign/pack filtering for fast find-and-clone
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_studio.py -v && node --check pipeline/studio/app.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/studio/index.html pipeline/studio/app.js pipeline/studio/README.md tests/test_studio.py
git commit -m "Add campaign/pack filter to the Activities filterbar"
git push
```

---

### Task 5: Full verification

**Files:** none new.

- [ ] **Step 1: Run the complete test suite**

Run: `python3 -m pytest tests/ -q && node --test tests/analytics.test.js && node --check pipeline/studio/app.js && node --check pipeline/studio/analytics.js`
Expected: all pass (postgres-embedded tests may skip if pgserver is unavailable on this machine — skips are acceptable, failures are not).

- [ ] **Step 2: Manual smoke test**

Start the API (`python3 pipeline/scripts/start_cplan.py` or the documented start command from `pipeline/api/README.md`), open the studio, and verify:
- "New pack" opens the pack drawer; checking 3 channels shows 3 rows; dates cascade from the first row; "Create 3 activities" persists and toasts.
- Duplicate icon on a table row opens a prefilled create drawer titled "Duplicate of …"; saving creates a new tracking ID.
- Campaign/pack dropdown filters the table; Clear resets it.

**Fallback when no browser/manual check is possible in this session:** run only the automated suite and state explicitly in the final report that the manual smoke test is outstanding.

- [ ] **Step 3: Final commit if anything changed**

```bash
git status --short
# commit + push any remaining changes with an accurate message
```
