const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const start = appSource.indexOf("function rgbToLab");
assert(start >= 0, "color functions must remain extractable");
globalThis.twoByTwoColorMappingValid = true;
vm.runInThisContext(appSource.slice(start));

const faces = ["U", "R", "F", "D", "L", "B"];
const solvedClusters = Object.fromEntries(faces.map((face, index) => [face, Array(4).fill(index)]));
const mapping = inferTwoByTwoColorMap(solvedClusters, faces);
assert(mapping, "a solved cube must produce a legal color mapping");
const facelets = faces.flatMap((face) => solvedClusters[face].map((cluster) => mapping[cluster]));
assert.equal(isLegalTwoByTwoFacelets(facelets), true);

const impossible = structuredClone(solvedClusters);
impossible.U[0] = 1;
impossible.R[0] = 0;
assert.equal(inferTwoByTwoColorMap(impossible, faces), null);

const palette = [
  [235, 235, 230], [210, 45, 35], [45, 165, 70],
  [235, 205, 45], [235, 115, 30], [45, 95, 205],
].map((rgb) => makeColorDescriptor(rgb, 0.7, 0.8));
const samplesByFace = Object.fromEntries(
  faces.map((face, index) => [face, Array(4).fill(palette[index])]),
);
const classified = assignBalancedColors2x2(samplesByFace, faces);
for (const face of faces) assert.equal(new Set(classified[face]).size, 1);
assert.equal(isLegalTwoByTwoFacelets(faces.flatMap((face) => classified[face])), true);
assert.equal(twoByTwoColorMappingValid, true);

console.log("two_by_two_color.test.js: all tests passed");
