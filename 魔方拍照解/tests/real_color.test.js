const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const colorStart = appSource.indexOf("function rgbToLab");
assert(colorStart >= 0, "color functions must remain extractable");
globalThis.twoByTwoColorMappingValid = true;
vm.runInThisContext(appSource.slice(colorStart));

const payload = JSON.parse(fs.readFileSync(0, "utf8"));

const faceOrder = ["U", "R", "F", "D", "L", "B"];
const expectedByGroup = {
  legacy: {
    U: "FFDRUFFBR",
    R: "ULRBRDURB",
    F: "ULBLFDDLL",
    D: "BUFBDD DUL".replaceAll(" ", ""),
    L: "DURRLDBUL",
    B: "FRLFBBUFR",
  },
  1: {
    U: "FBBBUDURR",
    R: "FBRFRDUFD",
    F: "LUUFFDUUR",
    D: "FLBBDLDDR",
    L: "DLBRLULUL",
    B: "DRLRBFFLB",
  },
  2: {
    U: "DLLLURLFU",
    R: "RBUFRDLRB",
    F: "URFDFURRB",
    D: "UUDBDDRBR",
    L: "LUFLLLFDB",
    B: "BBFFBFDUD",
  },
  5: {
    U: "UFBFURRBU",
    R: "RDUBRDDRL",
    F: "DUFBFLDUB",
    D: "LLRDDFUDB",
    L: "FLFRLRBLF",
    B: "RULBBUDFL",
  },
};
const groupIndex = process.argv.indexOf("--group");
const group = groupIndex >= 0 ? process.argv[groupIndex + 1] : "legacy";
const isTwoByTwo = ["3", "4", "6", "7"].includes(group);
const expected = isTwoByTwo ? null : Object.fromEntries(
  Object.entries(expectedByGroup[group]).map(([face, labels]) => [face, [...labels]]),
);

const samples = Object.fromEntries(
  faceOrder.map((face) => [
    face,
    payload[face].map((encoded, index) =>
      summarizePatchPixels(Uint8ClampedArray.from(Buffer.from(encoded, "base64")), !isTwoByTwo && index === 4),
    ),
  ]),
);
const actual = isTwoByTwo ? assignBalancedColors2x2(samples, faceOrder) : assignBalancedColors(samples, faceOrder);

if (isTwoByTwo) {
  const physicalByGroup = {
    3: { U: "OYWO", R: "WBBR", F: "RGBY", D: "ROOG", L: "BGYW", B: "RWYG" },
    4: { U: "RYWO", R: "WOYO", F: "RGWB", D: "BRYW", L: "YGGR", B: "BGBO" },
    6: { U: "RGWY", R: "OWOG", F: "RGYW", D: "RBYY", L: "WGOB", B: "OBRB" },
    7: { U: "RRWW", R: "OBOO", F: "RBBB", D: "YYOY", L: "YGGR", B: "WGGW" },
  };
  const physicalToLabel = { W: "U", R: "R", G: "F", Y: "D", O: "L", B: "B" };
  const physical = physicalByGroup[group];
  const semanticExpected = Object.fromEntries(
    faceOrder.map((face) => [face, [...physical[face]].map((color) => physicalToLabel[color])]),
  );
  assert.deepEqual(actual, semanticExpected);
  assert.equal(isLegalTwoByTwoFacelets(faceOrder.flatMap((face) => actual[face])), true);
  assert.equal(twoByTwoColorMappingValid, true);
  console.log("real 2x2 image color tests passed");
  process.exit(0);
}

if (process.env.COLOR_DEBUG === "1") {
  const brief = (descriptor) => ({
    rgb: descriptor.rgb.map((value) => Math.round(value)),
    lab: descriptor.lab.map((value) => Number(value.toFixed(1))),
    hue: Number(descriptor.hue.toFixed(3)),
    saturation: Number(descriptor.saturation.toFixed(3)),
    value: Number(descriptor.value.toFixed(3)),
    glare: Number(descriptor.glareFraction.toFixed(3)),
  });
  console.error("centers", JSON.stringify(Object.fromEntries(faceOrder.map((face) => [face, brief(samples[face][4])]))));
  for (const face of faceOrder) {
    for (let index = 0; index < 9; index += 1) {
      if (actual[face][index] === expected[face][index]) continue;
      const distances = Object.fromEntries(
        faceOrder.map((candidate) => [candidate, Number(robustColorDistance(samples[face][index], samples[candidate][4]).toFixed(2))]),
      );
      console.error(`${face}${index}`, JSON.stringify({
        expected: expected[face][index],
        actual: actual[face][index],
        sample: brief(samples[face][index]),
        distances,
      }));
    }
  }
}

assert.deepEqual(actual, expected);
console.log("real image color tests passed");
