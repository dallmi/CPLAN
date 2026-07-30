(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.CplanXlsx = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Minimal .xlsx writer, no dependencies.
  //
  // Why not CSV: the studio's exports are read in Excel, and CSV loses
  // everything Excel is being used for -- column widths, a frozen header, real
  // dates that sort, and above all outline groups. The pack export is a parent
  // row with its activities beneath it, and "expand and collapse the pack" is
  // an .xlsx feature (outlineLevel) that no CSV can carry. A generated CSV also
  // hands Excel a locale guessing game over separators and date order.
  //
  // Why not a library: the studio ships as three static files served from disk,
  // with no bundler and no CDN reachable from the corp network. An .xlsx is a
  // ZIP of a handful of XML parts, and writing exactly the parts we need is
  // less code than vendoring a general-purpose library would be.

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i += 1) {
      let c = i;
      for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      table[i] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i += 1) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  const encoder = new TextEncoder();

  // ZIP is written with STORE (method 0). Deflate would need CompressionStream,
  // which is async and not everywhere; an export of a few thousand rows is a
  // handful of megabytes uncompressed, which a local download handles fine.
  // Correctness over bytes: a valid archive every browser opens.
  function zip(files) {
    const parts = [];
    const central = [];
    let offset = 0;

    files.forEach(file => {
      const nameBytes = encoder.encode(file.name);
      const data = file.data;
      const sum = crc32(data);

      const local = new Uint8Array(30 + nameBytes.length);
      const lv = new DataView(local.buffer);
      lv.setUint32(0, 0x04034b50, true);   // local file header
      lv.setUint16(4, 20, true);           // version needed
      lv.setUint16(6, 0, true);            // flags
      lv.setUint16(8, 0, true);            // method: store
      lv.setUint16(10, 0, true);           // time
      lv.setUint16(12, 0x0021, true);      // date: 1980-01-01, fixed so the
                                           // same input always produces the
                                           // same bytes
      lv.setUint32(14, sum, true);
      lv.setUint32(18, data.length, true);
      lv.setUint32(22, data.length, true);
      lv.setUint16(26, nameBytes.length, true);
      lv.setUint16(28, 0, true);
      local.set(nameBytes, 30);

      parts.push(local, data);

      const dir = new Uint8Array(46 + nameBytes.length);
      const dv = new DataView(dir.buffer);
      dv.setUint32(0, 0x02014b50, true);   // central directory header
      dv.setUint16(4, 20, true);
      dv.setUint16(6, 20, true);
      dv.setUint16(8, 0, true);
      dv.setUint16(10, 0, true);
      dv.setUint16(12, 0, true);
      dv.setUint16(14, 0x0021, true);
      dv.setUint32(16, sum, true);
      dv.setUint32(20, data.length, true);
      dv.setUint32(24, data.length, true);
      dv.setUint16(28, nameBytes.length, true);
      dv.setUint32(42, offset, true);
      dir.set(nameBytes, 46);
      central.push(dir);

      offset += local.length + data.length;
    });

    const centralSize = central.reduce((n, c) => n + c.length, 0);
    const end = new Uint8Array(22);
    const ev = new DataView(end.buffer);
    ev.setUint32(0, 0x06054b50, true);     // end of central directory
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);

    return new Blob([...parts, ...central, end],
      {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      // Control characters are illegal in XML 1.0 and Excel refuses the whole
      // file over one of them. Source data has carried stray ones before.
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
  }

  function columnName(index) {
    let name = '';
    let n = index + 1;
    while (n > 0) {
      const rem = (n - 1) % 26;
      name = String.fromCharCode(65 + rem) + name;
      n = Math.floor((n - 1) / 26);
    }
    return name;
  }

  // Excel's day zero is 1899-12-30 (the 1900 leap-year bug is baked into the
  // format). Serials are written in the sheet's own frame of reference, so the
  // date is read back as the local wall-clock time the studio displays -- not
  // shifted by the reader's timezone.
  function dateSerial(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    const local = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate(),
      date.getHours(), date.getMinutes(), date.getSeconds());
    return (local / 86400000) + 25569;
  }

  const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`;

  const ROOT_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;

  const WORKBOOK_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;

  // Four cell styles, in this order: 0 plain, 1 header (bold on a fill),
  // 2 date/time, 3 bold (the pack summary rows).
  const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd\\ hh:mm"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFECEBE4"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

  function workbookXml(sheetName) {
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="${esc(sheetName)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>`;
  }

  function cellXml(ref, value, style) {
    if (value === null || value === undefined || value === '') {
      return style ? `<c r="${ref}" s="${style}"/>` : '';
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      return `<c r="${ref}"${style ? ` s="${style}"` : ''}><v>${value}</v></c>`;
    }
    return `<c r="${ref}"${style ? ` s="${style}"` : ''} t="inlineStr"><is><t xml:space="preserve">${esc(value)}</t></is></c>`;
  }

  /**
   * columns: [{header, width}]
   * rows:    [{cells: [...], level?: 0|1, bold?: boolean, collapsedChildren?: boolean}]
   *          A cell may be a primitive, or {date: <Date|string>} for a real
   *          date cell.
   */
  function build(options) {
    const sheetName = (options.sheetName || 'Sheet1').slice(0, 31);
    const columns = options.columns || [];
    const rows = options.rows || [];
    const grouped = rows.some(row => (row.level || 0) > 0);

    const cols = columns.length
      ? `<cols>${columns.map((c, i) =>
          `<col min="${i + 1}" max="${i + 1}" width="${c.width || 18}" customWidth="1"/>`).join('')}</cols>`
      : '';

    const header = `<row r="1" s="1" customFormat="1">${
      columns.map((c, i) => cellXml(`${columnName(i)}1`, c.header, 1)).join('')}</row>`;

    const body = rows.map((row, index) => {
      const r = index + 2;
      const level = row.level || 0;
      const style = row.bold ? 3 : 0;
      const cells = (row.cells || []).map((value, i) => {
        const ref = `${columnName(i)}${r}`;
        if (value && typeof value === 'object' && 'date' in value) {
          const serial = dateSerial(value.date);
          return serial === null ? cellXml(ref, '', style) : cellXml(ref, serial, 2);
        }
        return cellXml(ref, value, style);
      }).join('');
      // Child rows start hidden so the file opens showing one line per pack --
      // the overview the export exists for. Expanding is one click on the
      // outline control Excel draws in the margin.
      const hidden = level > 0 && options.collapsed ? ' hidden="1"' : '';
      return `<row r="${r}"${level ? ` outlineLevel="${level}"` : ''}${hidden}>${cells}</row>`;
    }).join('');

    // summaryBelow="0" puts the parent row ABOVE its children, which is how a
    // pack and its activities read. Excel's default is the other way round and
    // would attach every pack's control to the row beneath its last activity.
    const sheetPr = grouped
      ? '<sheetPr><outlinePr summaryBelow="0" summaryRight="0"/></sheetPr>'
      : '';
    const outlineState = grouped && options.collapsed
      ? ' outlineLevelRow="1"'
      : '';

    const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
${sheetPr}<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="15"${outlineState}/>
${cols}<sheetData>${header}${body}</sheetData>
<autoFilter ref="A1:${columnName(Math.max(0, columns.length - 1))}${rows.length + 1}"/>
</worksheet>`;

    return zip([
      {name: '[Content_Types].xml', data: encoder.encode(CONTENT_TYPES)},
      {name: '_rels/.rels', data: encoder.encode(ROOT_RELS)},
      {name: 'xl/workbook.xml', data: encoder.encode(workbookXml(sheetName))},
      {name: 'xl/_rels/workbook.xml.rels', data: encoder.encode(WORKBOOK_RELS)},
      {name: 'xl/styles.xml', data: encoder.encode(STYLES)},
      {name: 'xl/worksheets/sheet1.xml', data: encoder.encode(sheet)}
    ]);
  }

  return {build, columnName, dateSerial, crc32};
});
