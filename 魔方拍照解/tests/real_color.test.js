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
const expected = {
  U: ["F", "F", "D", "R", "U", "F", "F", "B", "R"],
  R: ["U", "L", "R", "B", "R", "D", "U", "R", "B"],
  F: ["U", "L", "B", "L", "F", "D", "D", "L", "L"],
  D: ["B", "U", "F", "B", "D", "D", "D", "U", "L"],
  L: ["D", "U", "R", "R", "L", "D", "B", "U", "L"],
  B: ["F", "R", "L", "F", "B", "B", "U", "F", "R"],
};

const samples = Object.fromEntries(
  faceOrder.map((face) => [
    face,
    payload[face].map((encoded, index) =>
      summarizePatchPixels(Uint8ClampedArray.from(Buffer.from(encoded, "base64")), index === 4),
    ),
  ]),
);
const actual = assignBalancedColors(samples, faceOrder);

assert.deepEqual(actual, expected);
console.log("real image color tests passed");
