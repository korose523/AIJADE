// Build the decimal sequence in bounded chunks.
const solve = n => {
  const chunks = [];
  let chunk = '0';
  for (let i = 1; i <= n; i++) {
    chunk += ' ' + i;
    if (i % 4096 === 0) {
      chunks.push(chunk);
      chunk = '';
    }
  }
  chunks.push(chunk);
  return chunks.join('');
};
