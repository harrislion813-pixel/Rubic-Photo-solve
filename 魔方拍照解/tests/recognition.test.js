const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class PixelCanvas {
  constructor(width = 1, height = 1) {
    this._width = width;
    this._height = height;
    this.data = new Uint8ClampedArray(width * height * 4);
  }

  get width() {
    return this._width;
  }

  set width(value) {
    this._width = value;
    this.data = new Uint8ClampedArray(this._width * this._height * 4);
  }

  get height() {
    return this._height;
  }

  set height(value) {
    this._height = value;
    this.data = new Uint8ClampedArray(this._width * this._height * 4);
  }

  getContext() {
    return {
      drawImage: (source, _x, _y, width = this.width, height = this.height) => {
        for (let y = 0; y < height; y += 1) {
          for (let x = 0; x < width; x += 1) {
            const sourceX = Math.min(source.width - 1, Math.floor((x / width) * source.width));
            const sourceY = Math.min(source.height - 1, Math.floor((y / height) * source.height));
            const sourceOffset = (sourceY * source.width + sourceX) * 4;
            const targetOffset = (y * this.width + x) * 4;
            this.data.set(source.data.subarray(sourceOffset, sourceOffset + 4), targetOffset);
          }
        }
      },
      getImageData: () => ({ width: this.width, height: this.height, data: this.data }),
    };
  }
}

global.document = { createElement: () => new PixelCanvas() };

const appSource = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const recognitionStart = appSource.indexOf("function fallbackFaceDetection");
const recognitionEnd = appSource.indexOf("function drawSampleGrid");
assert(recognitionStart >= 0 && recognitionEnd > recognitionStart, "recognition functions must remain extractable");
vm.runInThisContext(appSource.slice(recognitionStart, recognitionEnd));

function fill(canvas, color) {
  for (let offset = 0; offset < canvas.data.length; offset += 4) {
    canvas.data[offset] = color[0];
    canvas.data[offset + 1] = color[1];
    canvas.data[offset + 2] = color[2];
    canvas.data[offset + 3] = 255;
  }
}

function insidePolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i];
    const b = points[j];
    if ((a.y > y) !== (b.y > y) && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

function paintPolygon(canvas, points, color) {
  const minX = Math.max(0, Math.floor(Math.min(...points.map((point) => point.x))));
  const maxX = Math.min(canvas.width - 1, Math.ceil(Math.max(...points.map((point) => point.x))));
  const minY = Math.max(0, Math.floor(Math.min(...points.map((point) => point.y))));
  const maxY = Math.min(canvas.height - 1, Math.ceil(Math.max(...points.map((point) => point.y))));
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      if (!insidePolygon(x + 0.5, y + 0.5, points)) continue;
      const offset = (y * canvas.width + x) * 4;
      canvas.data[offset] = color[0];
      canvas.data[offset + 1] = color[1];
      canvas.data[offset + 2] = color[2];
      canvas.data[offset + 3] = 255;
    }
  }
}

function quadPoint(corners, u, v) {
  const top = {
    x: corners[0].x * (1 - u) + corners[1].x * u,
    y: corners[0].y * (1 - u) + corners[1].y * u,
  };
  const bottom = {
    x: corners[3].x * (1 - u) + corners[2].x * u,
    y: corners[3].y * (1 - u) + corners[2].y * u,
  };
  return { x: top.x * (1 - v) + bottom.x * v, y: top.y * (1 - v) + bottom.y * v };
}

function makePhoto(background, options = {}) {
  const canvas = new PixelCanvas(options.width || 400, options.height || 250);
  fill(canvas, background);
  paintPolygon(canvas, [{ x: 12, y: 25 }, { x: 55, y: 25 }, { x: 55, y: 112 }, { x: 12, y: 112 }], [104, 71, 48]);
  paintPolygon(canvas, [{ x: canvas.width - 75, y: 30 }, { x: canvas.width - 18, y: 30 }, { x: canvas.width - 18, y: 62 }, { x: canvas.width - 75, y: 62 }], [38, 75, 115]);

  const corners = options.corners || [
    { x: 105, y: 30 },
    { x: 281, y: 48 },
    { x: 300, y: 221 },
    { x: 86, y: 202 },
  ];
  paintPolygon(canvas, corners, [14, 17, 19]);
  const colors = [
    [244, 242, 234],
    [216, 59, 45],
    [45, 166, 75],
    [240, 210, 70],
    [235, 124, 34],
    [45, 101, 200],
    [216, 59, 45],
    [45, 166, 75],
    [244, 242, 234],
  ];
  const gap = 0.018;
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      paintPolygon(
        canvas,
        [
          quadPoint(corners, column / 3 + gap, row / 3 + gap),
          quadPoint(corners, (column + 1) / 3 - gap, row / 3 + gap),
          quadPoint(corners, (column + 1) / 3 - gap, (row + 1) / 3 - gap),
          quadPoint(corners, column / 3 + gap, (row + 1) / 3 - gap),
        ],
        colors[row * 3 + column],
      );
    }
  }
  return { canvas, corners };
}

for (const background of [[43, 49, 53], [232, 235, 237]]) {
  const { canvas, corners } = makePhoto(background);
  const detected = detectCubeFace(canvas);
  if (detected.mode !== "auto") {
    const imageData = canvas.getContext("2d").getImageData();
    const rawMask = buildStickerMask(imageData);
    console.log({ rawMaskCount: rawMask.reduce((sum, value) => sum + value, 0), firstPixel: Array.from(canvas.data.slice(0, 4)) });
    const closedMask = closeMask(rawMask, canvas.width, canvas.height, 5);
    const diagnostic = connectedComponents(closedMask, canvas.width, canvas.height)
      .filter((component) => component.boundary.length >= 4)
      .map((component) => {
        const boxWidth = component.maxX - component.minX + 1;
        const boxHeight = component.maxY - component.minY + 1;
        const corners = expandQuad(orderQuad(reduceHullToFour(convexHull(component.boundary))), 1.025, canvas.width, canvas.height);
        return {
          area: component.area,
          box: [component.minX, component.minY, component.maxX, component.maxY],
          score: scoreQuad(corners, rawMask, canvas.width, canvas.height, component.area / (boxWidth * boxHeight)),
        };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 8);
    console.log(diagnostic);
  }
  assert.equal(detected.mode, "auto");
  const meanCornerError = detected.corners.reduce(
    (sum, point, index) => sum + Math.hypot(point.x - corners[index].x, point.y - corners[index].y),
    0,
  ) / 4;
  assert(
    meanCornerError < 18,
    `mean corner error was ${meanCornerError.toFixed(1)}px: ${JSON.stringify(detected)}`,
  );
}

const smallFace = makePhoto([51, 55, 58], {
  width: 600,
  height: 360,
  corners: [
    { x: 250, y: 84 },
    { x: 396, y: 99 },
    { x: 410, y: 249 },
    { x: 237, y: 235 },
  ],
});
const smallDetected = detectCubeFace(smallFace.canvas);
assert.equal(smallDetected.mode, "auto");
const smallError = smallDetected.corners.reduce(
  (sum, point, index) => sum + Math.hypot(point.x - smallFace.corners[index].x, point.y - smallFace.corners[index].y),
  0,
) / 4;
assert(smallError < 20, `small-face corner error was ${smallError.toFixed(1)}px`);

const homographyCorners = [
  { x: 17, y: 23 },
  { x: 211, y: 31 },
  { x: 229, y: 205 },
  { x: 9, y: 191 },
];
const homography = solveHomography(homographyCorners);
[[0, 0], [1, 0], [1, 1], [0, 1]].forEach(([u, v], index) => {
  const denominator = homography[6] * u + homography[7] * v + 1;
  const x = (homography[0] * u + homography[1] * v + homography[2]) / denominator;
  const y = (homography[3] * u + homography[4] * v + homography[5]) / denominator;
  assert(Math.hypot(x - homographyCorners[index].x, y - homographyCorners[index].y) < 1e-6);
});

const blank = new PixelCanvas(400, 250);
fill(blank, [35, 38, 40]);
assert.equal(detectCubeFace(blank).mode, "fallback");

console.log("recognition tests passed");
