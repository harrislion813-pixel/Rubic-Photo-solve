export function rgbToLab(rgb) {
  let [r, g, b] = rgb.map((value) => value / 255);
  [r, g, b] = [r, g, b].map((value) => (
    value > 0.04045 ? ((value + 0.055) / 1.055) ** 2.4 : value / 12.92
  ));
  let x = r * 0.4124 + g * 0.3576 + b * 0.1805;
  let y = r * 0.2126 + g * 0.7152 + b * 0.0722;
  let z = r * 0.0193 + g * 0.1192 + b * 0.9505;
  x /= 0.95047;
  z /= 1.08883;
  const fx = labPivot(x);
  const fy = labPivot(y);
  const fz = labPivot(z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

function labPivot(value) {
  return value > 0.008856 ? Math.cbrt(value) : 7.787 * value + 16 / 116;
}

function labDistance(first, second) {
  return Math.hypot(first[0] - second[0], first[1] - second[1], first[2] - second[2]);
}

export function quantile(values, fraction) {
  if (!values.length) return 0;
  const sorted = [...values].sort((first, second) => first - second);
  const position = (sorted.length - 1) * Math.min(1, Math.max(0, fraction));
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

export function summarizePatchPixels(data, preferMajority = false) {
  const pixels = [];
  for (let index = 0; index < data.length; index += 4) {
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const maximum = Math.max(r, g, b);
    const minimum = Math.min(r, g, b);
    const value = maximum / 255;
    if (value < 0.12) continue;
    pixels.push({ r, g, b, value, saturation: (maximum - minimum) / Math.max(1, maximum) });
  }
  if (!pixels.length) return makeColorDescriptor([0, 0, 0], 0, 0, 0);

  const saturationSignal = quantile(
    pixels.map((pixel) => pixel.saturation), preferMajority ? 0.55 : 0.78,
  );
  const glareFraction = pixels.filter(
    (pixel) => pixel.value > 0.86 && pixel.saturation < 0.12,
  ).length / pixels.length;
  const saturatedFraction = pixels.filter(
    (pixel) => pixel.value > 0.16 && pixel.saturation > 0.24,
  ).length / pixels.length;
  const colorful = saturationSignal > 0.15
    || (!preferMajority && glareFraction > 0.45 && saturatedFraction > 0.04);
  const saturationFloor = colorful
    ? Math.max(0.10, quantile(pixels.map((pixel) => pixel.saturation), 0.42)) : 0;
  const brightnessCeiling = quantile(pixels.map((pixel) => pixel.value), 0.97);
  let selected = pixels.filter((pixel) => {
    if (!colorful) return true;
    const specular = pixel.value > Math.max(0.82, brightnessCeiling * 0.96)
      && pixel.saturation < saturationSignal * 0.55;
    return pixel.saturation >= saturationFloor && !specular;
  });
  if (selected.length < Math.max(12, pixels.length * 0.12)) selected = pixels;

  let weightTotal = 0;
  const rgb = [0, 0, 0];
  for (const pixel of selected) {
    const weight = colorful
      ? 0.15 + pixel.saturation * pixel.saturation * 3.2
      : Math.max(0.15, 1 - pixel.saturation * 2.5);
    rgb[0] += pixel.r * weight;
    rgb[1] += pixel.g * weight;
    rgb[2] += pixel.b * weight;
    weightTotal += weight;
  }
  rgb[0] /= weightTotal;
  rgb[1] /= weightTotal;
  rgb[2] /= weightTotal;
  return makeColorDescriptor(
    rgb,
    quantile(selected.map((pixel) => pixel.saturation), 0.65),
    quantile(selected.map((pixel) => pixel.value), 0.5),
    glareFraction,
  );
}

export function makeColorDescriptor(rgb, saturation, value, glareFraction = 0) {
  const [r, g, b] = rgb.map((channel) => channel / 255);
  const maximum = Math.max(r, g, b);
  const minimum = Math.min(r, g, b);
  const delta = maximum - minimum;
  let hue = 0;
  if (delta > 1e-6) {
    if (maximum === r) hue = ((g - b) / delta) % 6;
    else if (maximum === g) hue = (b - r) / delta + 2;
    else hue = (r - g) / delta + 4;
    hue = ((hue / 6) % 1 + 1) % 1;
  }
  return { rgb, lab: rgbToLab(rgb), hue, saturation, value, glareFraction };
}

export function robustColorDistance(sample, center) {
  const labCost = labDistance(sample.lab, center.lab) * 0.62;
  const saturationCost = Math.abs(sample.saturation - center.saturation) * 42;
  const brightnessCost = Math.abs(sample.value - center.value) * 9;
  let hueCost = 0;
  if (sample.saturation > 0.14 && center.saturation > 0.14) {
    const hueDifference = Math.abs(sample.hue - center.hue);
    hueCost = Math.min(hueDifference, 1 - hueDifference) * 42;
  } else if ((sample.saturation > 0.20) !== (center.saturation > 0.20)) {
    hueCost = 18;
  }
  return labCost + saturationCost + brightnessCost + hueCost;
}

export function minimumCostAssignment(costs) {
  const size = costs.length;
  if (!size || costs.some((row) => row.length !== size)) {
    throw new Error("颜色分配矩阵必须是非空方阵");
  }
  const rowPotential = Array(size + 1).fill(0);
  const columnPotential = Array(size + 1).fill(0);
  const matchedRow = Array(size + 1).fill(0);
  const path = Array(size + 1).fill(0);
  for (let row = 1; row <= size; row += 1) {
    matchedRow[0] = row;
    let column = 0;
    const minimum = Array(size + 1).fill(Number.POSITIVE_INFINITY);
    const used = Array(size + 1).fill(false);
    do {
      used[column] = true;
      const currentRow = matchedRow[column];
      let delta = Number.POSITIVE_INFINITY;
      let nextColumn = 0;
      for (let candidate = 1; candidate <= size; candidate += 1) {
        if (used[candidate]) continue;
        const reducedCost = costs[currentRow - 1][candidate - 1]
          - rowPotential[currentRow] - columnPotential[candidate];
        if (reducedCost < minimum[candidate]) {
          minimum[candidate] = reducedCost;
          path[candidate] = column;
        }
        if (minimum[candidate] < delta) {
          delta = minimum[candidate];
          nextColumn = candidate;
        }
      }
      for (let candidate = 0; candidate <= size; candidate += 1) {
        if (used[candidate]) {
          rowPotential[matchedRow[candidate]] += delta;
          columnPotential[candidate] -= delta;
        } else {
          minimum[candidate] -= delta;
        }
      }
      column = nextColumn;
    } while (matchedRow[column] !== 0);
    do {
      const previous = path[column];
      matchedRow[column] = matchedRow[previous];
      column = previous;
    } while (column !== 0);
  }
  const assignment = Array(size).fill(-1);
  for (let column = 1; column <= size; column += 1) {
    assignment[matchedRow[column] - 1] = column - 1;
  }
  return assignment;
}

function colorDescriptorMedoid(descriptors) {
  let best = descriptors[0];
  let bestCost = Number.POSITIVE_INFINITY;
  for (const candidate of descriptors) {
    const cost = descriptors.reduce(
      (sum, descriptor) => sum + robustColorDistance(candidate, descriptor), 0,
    );
    if (cost < bestCost) {
      best = candidate;
      bestCost = cost;
    }
  }
  return best;
}

function descriptorHasLittleInformation(descriptor) {
  return descriptor.value < 0.10
    || (descriptor.value > 0.97 && descriptor.saturation < 0.08)
    || descriptor.glareFraction > 0.82;
}

function buildQuality(items, prototypes, assignedGroups, mappingValid = true) {
  let minimumPrototypeDistance = Number.POSITIVE_INFINITY;
  for (let first = 0; first < prototypes.length; first += 1) {
    for (let second = first + 1; second < prototypes.length; second += 1) {
      minimumPrototypeDistance = Math.min(
        minimumPrototypeDistance,
        robustColorDistance(prototypes[first], prototypes[second]),
      );
    }
  }
  const stickerConfidence = items.map((item, row) => {
    const assigned = assignedGroups[row];
    const assignedCost = robustColorDistance(item.sample, prototypes[assigned]);
    const alternativeCost = Math.min(...prototypes.map((prototype, index) => (
      index === assigned ? Number.POSITIVE_INFINITY : robustColorDistance(item.sample, prototype)
    )));
    const margin = alternativeCost - assignedCost;
    return {
      confidence: Math.max(0, Math.min(1, (margin + 3) / 15)),
      margin,
      cost: assignedCost,
      low: margin < 2.5 || assignedCost > 38,
    };
  });
  const ambiguousFraction = stickerConfidence.filter((item) => item.low).length
    / Math.max(1, stickerConfidence.length);
  const lowInformationFraction = items.filter((item) => descriptorHasLittleInformation(item.sample)).length
    / Math.max(1, items.length);
  const reasons = [];
  if (minimumPrototypeDistance < 9) reasons.push("六种颜色在照片中无法可靠区分");
  if (lowInformationFraction > 0.45) reasons.push("照片过暗、过曝或反光区域过多");
  if (ambiguousFraction > 0.55) reasons.push("过多色块的颜色判断存在歧义");
  if (!mappingValid) reasons.push("颜色聚类无法组成合法的 8 个角块");
  return {
    valid: reasons.length === 0,
    reasons,
    minimumPrototypeDistance,
    ambiguousFraction,
    lowInformationFraction,
    stickerConfidence,
    mappingValid,
  };
}

export function classifyBalancedColors(samplesByFace, faceOrder) {
  const prototypesByFace = Object.fromEntries(
    faceOrder.map((face) => [face, samplesByFace[face][4]]),
  );
  const items = [];
  for (const face of faceOrder) {
    samplesByFace[face].forEach((sample, index) => {
      if (index !== 4) items.push({ face, index, sample });
    });
  }
  const slots = faceOrder.flatMap((face) => Array(8).fill(face));
  let assignment = [];
  for (let iteration = 0; iteration < 3; iteration += 1) {
    assignment = minimumCostAssignment(items.map((item) => (
      slots.map((candidate) => robustColorDistance(item.sample, prototypesByFace[candidate]))
    )));
    const groups = Object.fromEntries(faceOrder.map((face) => [face, [samplesByFace[face][4]]]));
    items.forEach((item, row) => groups[slots[assignment[row]]].push(item.sample));
    for (const face of faceOrder) prototypesByFace[face] = colorDescriptorMedoid(groups[face]);
  }
  const labels = Object.fromEntries(faceOrder.map((face) => [face, Array(9).fill(face)]));
  items.forEach((item, row) => { labels[item.face][item.index] = slots[assignment[row]]; });
  const prototypes = faceOrder.map((face) => prototypesByFace[face]);
  const assignedGroups = assignment.map((slot) => faceOrder.indexOf(slots[slot]));
  const quality = buildQuality(items, prototypes, assignedGroups);
  const confidenceByFace = Object.fromEntries(faceOrder.map((face) => [face, Array(9).fill(null)]));
  items.forEach((item, row) => { confidenceByFace[item.face][item.index] = quality.stickerConfidence[row]; });
  return { labels, confidenceByFace, quality };
}

export function classifyBalancedColors2x2(samplesByFace, faceOrder) {
  const items = faceOrder.flatMap((face) => (
    samplesByFace[face].map((sample, index) => ({ face, index, sample }))
  ));
  const prototypes = [items[0].sample];
  while (prototypes.length < 6) {
    let best = items[0].sample;
    let bestDistance = -1;
    for (const item of items) {
      const nearest = Math.min(
        ...prototypes.map((prototype) => robustColorDistance(item.sample, prototype)),
      );
      if (nearest > bestDistance) {
        best = item.sample;
        bestDistance = nearest;
      }
    }
    prototypes.push(best);
  }
  const slots = Array.from({ length: 6 }, (_, cluster) => Array(4).fill(cluster)).flat();
  let assignment = [];
  for (let iteration = 0; iteration < 5; iteration += 1) {
    assignment = minimumCostAssignment(
      items.map((item) => slots.map((cluster) => robustColorDistance(item.sample, prototypes[cluster]))),
    );
    for (let cluster = 0; cluster < 6; cluster += 1) {
      const group = items.filter((_, row) => slots[assignment[row]] === cluster).map((item) => item.sample);
      prototypes[cluster] = colorDescriptorMedoid(group);
    }
  }
  const clusters = Object.fromEntries(faceOrder.map((face) => [face, Array(4).fill(-1)]));
  items.forEach((item, row) => { clusters[item.face][item.index] = slots[assignment[row]]; });
  const colorMap = inferPhysicalTwoByTwoColorMap(prototypes, clusters, faceOrder)
    || inferTwoByTwoColorMap(clusters, faceOrder);
  const mappingValid = colorMap !== null;
  const effectiveMap = colorMap || faceOrder;
  const labels = Object.fromEntries(
    faceOrder.map((face) => [face, clusters[face].map((cluster) => effectiveMap[cluster])]),
  );
  const assignedGroups = assignment.map((slot) => slots[slot]);
  const quality = buildQuality(items, prototypes, assignedGroups, mappingValid);
  const confidenceByFace = Object.fromEntries(faceOrder.map((face) => [face, Array(4).fill(null)]));
  items.forEach((item, row) => { confidenceByFace[item.face][item.index] = quality.stickerConfidence[row]; });
  return { labels, confidenceByFace, quality };
}

export function assignBalancedColors2x2(samplesByFace, faceOrder) {
  return classifyBalancedColors2x2(samplesByFace, faceOrder).labels;
}

function inferPhysicalTwoByTwoColorMap(prototypes, clusters, faceOrder) {
  const canonical = [
    makeColorDescriptor([238, 238, 232], 0.03, 0.93),
    makeColorDescriptor([215, 45, 35], 0.84, 0.84),
    makeColorDescriptor([42, 166, 72], 0.75, 0.65),
    makeColorDescriptor([242, 213, 55], 0.77, 0.95),
    makeColorDescriptor([240, 115, 27], 0.89, 0.94),
    makeColorDescriptor([43, 101, 201], 0.79, 0.79),
  ];
  const assignment = minimumCostAssignment(
    prototypes.map((prototype) => canonical.map((reference) => robustColorDistance(prototype, reference))),
  );
  const mapping = assignment.map((labelIndex) => faceOrder[labelIndex]);
  const facelets = faceOrder.flatMap((face) => clusters[face].map((cluster) => mapping[cluster]));
  return isLegalTwoByTwoFacelets(facelets) ? mapping : null;
}

export function inferTwoByTwoColorMap(clusters, faceOrder) {
  const remainingLabels = ["R", "F", "D", "L", "B"];
  let result = null;
  function visit(prefix, unused) {
    if (result) return;
    if (!unused.length) {
      const mapping = ["U", ...prefix];
      const facelets = faceOrder.flatMap((face) => clusters[face].map((cluster) => mapping[cluster]));
      if (isLegalTwoByTwoFacelets(facelets)) result = mapping;
      return;
    }
    unused.forEach((label, index) => {
      visit([...prefix, label], [...unused.slice(0, index), ...unused.slice(index + 1)]);
    });
  }
  visit([], remainingLabels);
  return result;
}

export function isLegalTwoByTwoFacelets(facelets) {
  const cornerIndices = [
    [3, 4, 9], [2, 8, 17], [0, 16, 21], [1, 20, 5],
    [13, 11, 6], [12, 19, 10], [14, 23, 18], [15, 7, 22],
  ];
  const cornerColors = [
    ["U", "R", "F"], ["U", "F", "L"], ["U", "L", "B"], ["U", "B", "R"],
    ["D", "F", "R"], ["D", "L", "F"], ["D", "B", "L"], ["D", "R", "B"],
  ];
  const cubies = [];
  let orientationSum = 0;
  for (const indices of cornerIndices) {
    const orientation = indices.findIndex(
      (index) => facelets[index] === "U" || facelets[index] === "D",
    );
    if (orientation < 0) return false;
    const color1 = facelets[indices[(orientation + 1) % 3]];
    const color2 = facelets[indices[(orientation + 2) % 3]];
    const cubie = cornerColors.findIndex((colors) => colors[1] === color1 && colors[2] === color2);
    if (cubie < 0) return false;
    cubies.push(cubie);
    orientationSum += orientation;
  }
  return new Set(cubies).size === 8 && orientationSum % 3 === 0;
}
