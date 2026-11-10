// Cartesian product of the three offsets in each dimension, in input order.
const solve = coordinates => {
  let rows = [[]];
  for (const value of coordinates) {
    const next = [];
    for (const prefix of rows) {
      for (let offset = -1; offset <= 1; offset++) next.push([...prefix, value + offset]);
    }
    rows = next;
  }
  return rows;
};
