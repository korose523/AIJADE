function solve(numbers, threshold) {
  for (let i = 0; i < numbers.length; i++)
    for (let j = i + 1; j < numbers.length; j++)
      if (Math.abs(numbers[i] - numbers[j]) < threshold) return true;
  return false;
}