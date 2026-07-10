const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const colorStart = appSource.indexOf("function rgbToLab");
assert(colorStart >= 0, "color functions must remain extractable");
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
};
const groupIndex = process.argv.indexOf("--group");
const group = groupIndex >= 0 ? process.argv[groupIndex + 1] : "legacy";
const expected = Object.fromEntries(
  Object.entries(expectedByGroup[group]).map(([face, labels]) => [face, [...labels]]),
);

const samples = Object.fromEntries(
  faceOrder.map((face) => [
    face,
    payload[face].map((encoded, index) =>
      summarizePatchPixels(Uint8ClampedArray.from(Buffer.from(encoded, "base64")), index === 4),
    ),
  ]),
);
const actual = assignBalancedColors(samples, faceOrder);

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
