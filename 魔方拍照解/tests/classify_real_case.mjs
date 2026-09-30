import fs from "node:fs";
import { classifyBalancedColors, summarizePatchPixels } from "../web/color.js";

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const faces = ["U", "R", "F", "D", "L", "B"];
const samples = Object.fromEntries(faces.map((face) => [
  face,
  payload[face].map((encoded, index) =>
    summarizePatchPixels(Uint8ClampedArray.from(Buffer.from(encoded, "base64")), index === 4)),
]));
const result = classifyBalancedColors(samples, faces);
console.log(JSON.stringify({
  labels: Object.fromEntries(faces.map((face) => [face, result.labels[face].join("")])),
  quality: result.quality,
}));
