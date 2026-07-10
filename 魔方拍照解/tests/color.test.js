const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const colorStart = appSource.indexOf("function rgbToLab");
assert(colorStart >= 0, "color functions must remain extractable");
vm.runInThisContext(appSource.slice(colorStart));

function patchPixels(parts) {
  const pixels = [];
  for (const [count, rgb] of parts) {
    for (let index = 0; index < count; index += 1) pixels.push(...rgb, 255);
  }
  return Uint8ClampedArray.from(pixels);
}

const glareGreen = summarizePatchPixels(
  patchPixels([
    [550, [38, 165, 68]],
    [450, [248, 248, 248]],
  ]),
);
const solidGreen = summarizePatchPixels(patchPixels([[1000, [38, 165, 68]]]));
const white = summarizePatchPixels(
  patchPixels([
    [800, [232, 232, 228]],
    [200, [255, 255, 255]],
  ]),
);
const whiteCenterWithBlueLogo = summarizePatchPixels(
  patchPixels([
    [700, [232, 232, 228]],
    [300, [35, 105, 205]],
  ]),
  true,
);

assert(glareGreen.saturation > 0.55, `green saturation was ${glareGreen.saturation}`);
assert(white.saturation < 0.06, `white saturation was ${white.saturation}`);
assert(
  whiteCenterWithBlueLogo.saturation < 0.12,
  `logo-contaminated white center saturation was ${whiteCenterWithBlueLogo.saturation}`,
);
assert(
  robustColorDistance(glareGreen, solidGreen) < robustColorDistance(glareGreen, white),
  "specular green must remain closer to green than white",
);

const palette = [
  [235, 235, 230],
  [210, 45, 35],
  [45, 165, 70],
  [235, 205, 45],
  [235, 115, 30],
  [45, 95, 205],
].map((rgb) => summarizePatchPixels(patchPixels([[500, rgb]])));
const samples = palette.flatMap((descriptor, colorIndex) =>
  Array.from({ length: 8 }, (_, sampleIndex) =>
    colorIndex === 2 && sampleIndex < 3
      ? summarizePatchPixels(
          patchPixels([
            [300, [45, 165, 70]],
            [200, [250, 250, 250]],
          ]),
        )
      : descriptor,
  ),
);
const slots = palette.flatMap((_, colorIndex) => Array(8).fill(colorIndex));
const costs = samples.map((sample) => slots.map((slot) => robustColorDistance(sample, palette[slot])));
const assignment = minimumCostAssignment(costs);
const counts = Array(6).fill(0);
assignment.forEach((column) => {
  counts[slots[column]] += 1;
});
assert.deepEqual(counts, [8, 8, 8, 8, 8, 8]);

console.log("color tests passed");
