// Evaluate the released arithmetic grammar with exact integer operations.
const solve = (operators, operands) => {
  if (operators.length + 1 !== operands.length) throw new Error('operator/operand arity');
  const tokens = [];
  for (let i = 0; i < operands.length; i++) {
    if (typeof operands[i] !== 'bigint') throw new Error('integer operand required');
    if (operands[i] < 0n) tokens.push('-', -operands[i]);
    else tokens.push(operands[i]);
    if (i < operators.length) {
      if (!['+', '-', '*', '//', '**'].includes(operators[i])) throw new Error('unsupported operator');
      tokens.push(operators[i]);
    }
  }
  let index = 0;
  function unary() {
    if (tokens[index] === '+' || tokens[index] === '-') {
      const sign = tokens[index++];
      const value = unary();
      return sign === '-' ? -value : value;
    }
    const value = tokens[index++];
    if (typeof value !== 'bigint') throw new Error('invalid operand');
    if (tokens[index] !== '**') return value;
    index++;
    return $p.op('pow', value, unary());
  }
  function product() {
    let value = unary();
    while (tokens[index] === '*' || tokens[index] === '//') {
      const operation = tokens[index++];
      value = $p.op(operation === '*' ? 'mul' : 'floor', value, unary());
    }
    return value;
  }
  let value = product();
  while (tokens[index] === '+' || tokens[index] === '-') {
    const operation = tokens[index++];
    value = $p.op(operation === '+' ? 'add' : 'sub', value, product());
  }
  if (index !== tokens.length) throw new Error('invalid expression');
  return value;
};
