/*
 * The file the smoke test drives the application with.
 *
 * Small on purpose: 13 KB + 16 KB, one grid, three properties (one scalar, one
 * ×3 vector, one ×6). A bigger file makes the pass slower without making it
 * more revealing — a broken component is broken on two cells as much as on two
 * million. Override with FESPP_SMOKE_EPC to drive the same gestures on another
 * file; the property names then have to be given too (FESPP_SMOKE_PROPS).
 */
import fs from 'node:fs';
import path from 'node:path';

const DATA_DIR = process.env.FESPP_SMOKE_DATA
  || path.resolve(import.meta.dirname, '..', '..', '..', 'data', 'private');

const EPC = process.env.FESPP_SMOKE_EPC || 'vector_props.epc';
const PROPS = (process.env.FESPP_SMOKE_PROPS || 'poro,velocity').split(',');

const epcPath = path.join(DATA_DIR, EPC);
const h5Path = epcPath.replace(/\.epc$/i, '.h5');

export const DATASET = {
  // Both files are handed to the file input: the EPC declares the objects, the
  // HDF5 holds their values.
  files: [epcPath, ...(fs.existsSync(h5Path) ? [h5Path] : [])],
  // Two properties of the same grid: one is enough to colour it, two are what
  // the Statistics view needs to set rows side by side.
  properties: PROPS,
  // A folder row of the tree — the context menu must NOT offer the value
  // actions on it.
  folder: process.env.FESPP_SMOKE_FOLDER || 'properties',
  missing: !fs.existsSync(epcPath) ? epcPath : null,
};
