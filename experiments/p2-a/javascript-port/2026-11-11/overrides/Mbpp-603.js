let largestLimit = 0;
let largestResult = [];
const solve = value => {
  const n = Number(value);
  if (n <= largestLimit) return largestResult.filter(x => x <= n);
  const values = new Array(n);
  for (let i = 0; i < n; i++) values[i] = i + 1;
  for (let index = 1; index < values.length; index++) {
    const step = values[index];
    let write = index + step;
    if (write >= values.length) continue;
    for (let read = write + 1; read < values.length; read++) {
      if ((read - index) % step !== 0) values[write++] = values[read];
    }
    values.length = write;
  }
  largestLimit = n;
  largestResult = values;
  return values.slice();
};
