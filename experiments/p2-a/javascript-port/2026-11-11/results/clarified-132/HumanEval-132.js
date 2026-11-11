// Track whether each open bracket contains a fully matched inner pair.
const solve = text => {
  const stack = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '[') stack.push(false);
    else if (stack.length !== 0) {
      if (stack.pop()) return true;
      if (stack.length !== 0) stack[stack.length - 1] = true;
    }
  }
  return false;
};
