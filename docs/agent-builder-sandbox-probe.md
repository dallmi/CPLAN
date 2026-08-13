# Probing the Agent Builder sandbox

One question decides how a drawn board can reach a chat, and it cannot be
answered by reading documentation: **can the agent's code interpreter open a
knowledge file as a file, or does that file's content only reach it as
retrieved text?**

- **It can `open()` them.** The drawing code and a font ship as knowledge files
  and the agent runs a few lines of bootstrap. Small prompt, whole code, and a
  bundled face means two people get the same board.
- **Retrieval only.** The agent has to write the drawing code into its own code
  cell verbatim. That caps the code at what a model will reliably reproduce,
  and a font — tens of kilobytes of base64 — is out of reach.

Everything about the delivery follows from which of those is true, so it is
worth five minutes to find out rather than five days to discover.

Nothing needs uploading for this. The probe runs against a file the agent
already holds.

## 1. Get the reference values

On the machine that built the delivery, in the `upload\` folder — either
`pipeline\output\agent-builder\upload` or the same folder under the synced
CPLAN directory, depending on which one `agentpack` found:

```powershell
Get-Item .\13-contract-head-of-communications-overview.txt | Select-Object Length
Get-FileHash -Algorithm SHA256 .\13-contract-head-of-communications-overview.txt
```

Use what that prints. It is the file the agent actually has, and it is the only
authority: the contract's text changes whenever the contract changes, and
Windows writes CRLF where this repository holds LF, which alone moves the byte
count and the hash.

## 2. Paste this into the agent

```
Run this as a diagnostic. Do not answer from anything you have read
before — every line below must come from code you actually execute in
this turn. If you have no way to execute code, say exactly that and stop.

Step 1 — is there a runtime at all?
Run:
    import sys, os, platform
    print(platform.python_version(), os.getcwd())
Report both values verbatim.

Step 2 — is there a filesystem, and are the knowledge files on it?
Run:
    import os
    for root in (os.getcwd(), "/mnt/data", "/data", "/tmp", "."):
        try:
            print(root, "->", sorted(os.listdir(root))[:40])
        except Exception as e:
            print(root, "-> ERROR", type(e).__name__)
Report the output exactly as printed, including the errors.

Step 3 — can you read one of them as a file?
Pick 13-contract-head-of-communications-overview.txt from whichever
directory Step 2 found it in. If Step 2 found it nowhere, say so and
stop — do not substitute anything you remember.
Run:
    import hashlib, pathlib
    p = pathlib.Path(<the path Step 2 found>)
    b = p.read_bytes()
    print(len(b))
    print(hashlib.sha256(b).hexdigest())
    print(repr(b[-60:]))
Report the three values.

Rules for this diagnostic:
- Never reconstruct a file's contents from memory or from retrieved
  text. If open() fails, the correct answer is that it failed.
- Do not draw anything, do not open a board file, do not summarise the
  pack.
- If any step cannot run, name the step and the reason in one sentence.
```

## 3. Read the answer

| What comes back | What it means |
|---|---|
| Step 1 fails | No code interpreter. A drawn board is not reachable from inside the agent at all — the picture has to be produced elsewhere and handed over. |
| Step 1 runs, Step 2 lists the knowledge files | The good case. Code and font ship as files; the agent runs a short bootstrap. |
| Step 2 finds nothing, Step 3 stops | The sandbox cannot see the knowledge. The drawing code has to be small enough for the agent to reproduce verbatim, and a bundled font is out. |
| Step 3 returns a hash although Step 2 was empty | It reconstructed rather than read. Treat exactly as "cannot see the knowledge". |

**Step 2 is the answer; step 3 is the cross-check.** If the byte count and the
hash match what PowerShell printed, it genuinely read the file. If the byte
count differs while everything else looks plausible, it hashed the text it had
in context — which is a no, not a yes.

The last 60 bytes are the third guard: retrieval rarely carries a file's tail.
For the contract as it stands they end on

    An object failing one of these is corrected, not explained.

but check that against the file rather than against this line, for the same
reason the byte count is computed rather than quoted.

## Why the probe is shaped this way

An agent holding the file's text in its context can produce a convincing
account of having read it. Each step is chosen so that it cannot:

- **`os.getcwd()`** is not something a model knows about its own sandbox.
- **A directory listing** is either there or it is not, and an invented one
  rarely matches the numbering exactly.
- **A SHA-256 over bytes** cannot be produced without running code, and code
  run over text recovered from context hashes the *context*, which differs from
  the file in line endings and in whatever retrieval trimmed.

The instruction "if `open()` fails, the correct answer is that it failed" is
doing real work. Without it the helpful answer and the true answer point in
opposite directions, and the helpful one is what arrives.

---

# Probe 2 — what the sandbox can draw with

Probe 1 answers whether the drawing code can *arrive*. Three things decide
whether it can *run*, and each of them kills a different part of the design if
the answer is no.

- **Is Pillow there?** Nothing can be installed in a sandbox with no network,
  so a missing library is final rather than inconvenient.
- **Does an image the code writes reach the chat?** A PNG on a sandbox
  filesystem that nobody can see is not a delivered board.
- **What faces does it have?** This decides whether a font has to ship at all.
  A sandbox holding one single-weight face draws a correct board whose
  hierarchy is carried by size alone — worth knowing before shipping tens of
  kilobytes of base64 to avoid it.

## Paste this into the agent

```
Second diagnostic. Same rules: every line must come from code you
actually run in this turn, and a step that cannot run is reported as
having failed rather than described.

Step 1 — is Pillow available?
Run:
    try:
        import PIL
        from PIL import Image, ImageDraw, ImageFont
        print("pillow", PIL.__version__)
    except Exception as e:
        print("pillow MISSING", type(e).__name__, e)
Report the line verbatim.

Step 2 — what faces does this machine have?
Run:
    import os
    roots = ["/usr/share/fonts", "/usr/local/share/fonts",
             "/Library/Fonts", "/System/Library/Fonts",
             "C:/Windows/Fonts", os.path.expanduser("~/.fonts")]
    found = []
    for r in roots:
        for dirpath, _, names in os.walk(r):
            for n in names:
                if n.lower().endswith((".ttf", ".ttc", ".otf")):
                    found.append(os.path.join(dirpath, n))
    print(len(found), "font files")
    for p in sorted(found)[:25]:
        print("   ", p)
Report the count and the list.

Step 3 — can you run code that arrived as a knowledge file?
From the directory probe 1 found, read any one of the .txt knowledge
files and print its first line, using open() rather than memory. Then
run:
    code = "VALUE = 6 * 7\n"
    ns = {}
    exec(code, ns)
    print("exec works:", ns["VALUE"])
Report both.

Step 4 — does an image you create reach me?
Run:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 380, 100], outline="#e60000", width=3)
    d.text((40, 55), "probe 2", fill="#000000")
    img.save("probe2.png")
    import os; print("wrote", os.path.abspath("probe2.png"),
                     os.path.getsize("probe2.png"), "bytes")
Then show me that image in this chat, and say plainly whether you were
able to display it or only to write the file.
```

## Read the answer

| What comes back | What it means |
|---|---|
| Step 1 says MISSING | Pillow is out. The board would have to be drawn with whatever *is* there, or not drawn in the agent at all. |
| Step 2 lists no fonts | A face has to ship as base64 — not an optimisation but the only way to get type on the page. |
| Step 2 lists one single-weight face | A font ships if the weight ladder matters; otherwise the board is correct and flatter. |
| Step 3 fails on `exec` | The code cannot be shipped as a file after all, whatever probe 1 said. Back to reproducing it verbatim, and small. |
| Step 4 writes but cannot display | The last mile is missing: the picture exists where nobody can see it, and the delivery needs a different final hop. |

**Step 4 is the one to read first.** A board the agent can draw and cannot hand
over is the same as no board, and it is the step most easily assumed to work.
