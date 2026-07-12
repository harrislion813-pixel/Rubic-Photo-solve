const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function main() {
const {
  classifyBalancedColors,
  makeColorDescriptor,
  minimumCostAssignment,
  robustColorDistance,
  summarizePatchPixels,
} = await import(pathToFileURL(path.join(__dirname, "..", "web", "color.js")).href);

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

const darkRed = summarizePatchPixels(patchPixels([[1000, [125, 16, 8]]]));
const darkOrange = summarizePatchPixels(patchPixels([[1000, [189, 53, 9]]]));
const brightRed = summarizePatchPixels(patchPixels([[1000, [221, 50, 31]]]));
const warmBrightRed = summarizePatchPixels(patchPixels([[1000, [220, 63, 37]]]));
const brightOrange = summarizePatchPixels(patchPixels([[1000, [252, 142, 45]]]));
assert(
  robustColorDistance(brightRed, darkRed) < robustColorDistance(brightRed, darkOrange),
  "a brightly lit red sticker must remain closer to a dark red center than orange",
);
assert(
  robustColorDistance(warmBrightRed, darkRed) < robustColorDistance(warmBrightRed, darkOrange),
  "a warm, brightly lit red sticker must not drift into the orange cluster",
);
assert(
  robustColorDistance(brightOrange, darkOrange) < robustColorDistance(brightOrange, darkRed),
  "a brightly lit orange sticker must remain closer to a dark orange center than red",
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

const faces = ["U", "R", "F", "D", "L", "B"];
const identical = makeColorDescriptor([220, 220, 220], 0, 0.86);
const unsafe = classifyBalancedColors(
  Object.fromEntries(faces.map((face) => [face, Array(9).fill(identical)])),
  faces,
);
assert.equal(unsafe.quality.valid, false, "indistinguishable colors must block automatic solving");
assert(unsafe.quality.reasons.some((reason) => reason.includes("无法可靠区分")));

console.log("color tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
