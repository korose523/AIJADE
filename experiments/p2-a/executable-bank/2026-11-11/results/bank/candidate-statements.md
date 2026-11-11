# P2-A candidate statements for author review

This book contains the 422 proposed statements and calling contracts. Author decisions are pending. The sortable task checklist and per-case decisions remain in the candidate-review archive. Each task defines a top-level solve callable and receives freshly parsed arguments.

## HumanEval/0

Check if in given list of numbers, are any two numbers closer to each other than
given threshold.

Arguments are provided in this order (numbers, threshold). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/0. Retained base cases 7. Retained extended cases 999.

## HumanEval/1

Input to this function is a string containing multiple groups of nested parentheses. Your goal is to
separate those group into separate strings and return the list of those.
Separate groups are balanced (each open brace is properly closed) and not nested within each other
Ignore any spaces in the input string.

Arguments are provided in this order (paren_string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/1. Retained base cases 4. Retained extended cases 83.

## HumanEval/3

You're given a list of deposit and withdrawal operations on a bank account that starts with
zero balance. Your task is to detect if at any point the balance of account fallls below zero, and
at that point function should return True. Otherwise it should return False.

Arguments are provided in this order (operations). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/3. Retained base cases 6. Retained extended cases 898.

## HumanEval/5

Insert a number 'delimeter' between every two consecutive elements of input list `numbers'

Arguments are provided in this order (numbers, delimeter). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/5. Retained base cases 3. Retained extended cases 153.

## HumanEval/6

Input to this function is a string represented multiple groups for nested parentheses separated by spaces.
For each of the group, output the deepest level of nesting of parentheses.
E.g. (()()) has maximum two levels of nesting while ((())) has three.

Arguments are provided in this order (paren_string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/6. Retained base cases 3. Retained extended cases 66.

## HumanEval/7

Filter an input list of strings only for ones that contain given substring

Arguments are provided in this order (strings, substring). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/7. Retained base cases 4. Retained extended cases 178.

## HumanEval/8

For a given list of integers, return a tuple consisting of a sum and a product of all the integers in a list.
Empty sum should be equal to 0 and empty product should be equal to 1.
Sum and product of integer values, including empty identities.
Each list element represents an integer. Boolean elements are excluded.

Arguments are provided in this order (numbers). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/8. Retained base cases 5. Retained extended cases 997.

## HumanEval/9

From a given list of integers, generate a list of rolling maximum element found until given moment
in the sequence.

Arguments are provided in this order (numbers). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/9. Retained base cases 4. Retained extended cases 959.

## HumanEval/10

Find the shortest palindrome that begins with a supplied string.
Algorithm idea is simple:
- Find the longest postfix of supplied string that is a palindrome.
- Append to the end of the string reverse of a string prefix that comes before the palindromic suffix.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/10. Retained base cases 5. Retained extended cases 780.

## HumanEval/11

Input are two strings a and b consisting only of 1s and 0s.
Perform binary XOR on these inputs and return result also as a string.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/11. Retained base cases 3. Retained extended cases 405.

## HumanEval/13

Return a greatest common divisor of two integers a and b

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/13. Retained base cases 4. Retained extended cases 987.

## HumanEval/14

Return list of all prefixes from shortest to longest of the input string

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/14. Retained base cases 3. Retained extended cases 903.

## HumanEval/15

Return a string containing space-delimited numbers starting from 0 upto n inclusive.
Decimal sequence 0 through n with one space between terms.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/15. Retained base cases 3. Retained extended cases 134.

## HumanEval/16

Given a string, find out how many distinct characters (regardless of case) does it consist of

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/16. Retained base cases 5. Retained extended cases 1000.

## HumanEval/17

Input to this function is a string representing musical notes in a special ASCII format.
Your task is to parse this string and return list of integers corresponding to how many beats does each
not last.

Here is a legend:
'o' - whole note, lasts four beats
'o|' - half note, lasts two beats
'.|' - quater note, lasts one beat

Arguments are provided in this order (music_string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/17. Retained base cases 5. Retained extended cases 215.

## HumanEval/18

Find how many times a given substring can be found in the original string. Count overlaping cases.

Arguments are provided in this order (string, substring). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/18. Retained base cases 4. Retained extended cases 1000.

## HumanEval/19

Input is a space-delimited string of numberals from 'zero' to 'nine'.
Valid choices are 'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight' and 'nine'.
Return the string with numbers sorted from smallest to largest

Arguments are provided in this order (numbers). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/19. Retained base cases 5. Retained extended cases 128.

## HumanEval/23

Return length of given string

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/23. Retained base cases 3. Retained extended cases 964.

## HumanEval/24

For a given number n, find the largest number that divides n evenly, smaller than n

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/24. Retained base cases 5. Retained extended cases 168.

## HumanEval/25

Return list of prime factors of given integer in the order from smallest to largest.
Each of the factors should be listed number of times corresponding to how many times it appeares in factorization.
Input number should be equal to the product of all factors

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/25. Retained base cases 8. Retained extended cases 138.

## HumanEval/26

From a list of integers, remove all elements that occur more than once.
Keep order of elements left the same as in the input.

Arguments are provided in this order (numbers). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/26. Retained base cases 3. Retained extended cases 862.

## HumanEval/29

Filter an input list of strings only for ones that start with a given prefix.

Arguments are provided in this order (strings, prefix). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/29. Retained base cases 2. Retained extended cases 996.

## HumanEval/30

Return only positive numbers in the list.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task HumanEval/30. Retained base cases 4. Retained extended cases 999.

## HumanEval/31

Return true if a given number is prime, and false otherwise.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/31. Retained base cases 13. Retained extended cases 154.

## HumanEval/35

Return maximum element in the list.
Greatest member of a nonempty numeric sequence.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task HumanEval/35. Retained base cases 2. Retained extended cases 938.

## HumanEval/36

Return the number of times the digit 7 appears in integers less than n which are divisible by 11 or 13.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/36. Retained base cases 8. Retained extended cases 148.

## HumanEval/39

prime_fib returns n-th number that is a Fibonacci number and it's also prime.
Positive Fibonacci-prime rank, checked by fast doubling and independent small-prime witnesses.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/39. Retained base cases 10. Retained extended cases 2.

## HumanEval/40

triples_sum_to_zero takes a list of integers as an input.
it returns True if there are three distinct elements in the list that
sum to zero, and False otherwise.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/40. Retained base cases 9. Retained extended cases 979.

## HumanEval/41

Imagine a road that's a perfectly straight infinitely long line.
n cars are driving left to right;  simultaneously, a different set of n cars
are driving right to left.   The two sets of cars start out being very far from
each other.  All cars move in the same speed.  Two cars are said to collide
when a car that's moving left to right hits a car that's moving right to left.
However, the cars are infinitely sturdy and strong; as a result, they continue moving
in their trajectory as if they did not collide.

This function outputs the number of such collisions.
Every car in one group meets each car in the other group once.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/41. Retained base cases 5. Retained extended cases 78.

## HumanEval/42

Return list with elements incremented by 1.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task HumanEval/42. Retained base cases 3. Retained extended cases 999.

## HumanEval/43

pairs_sum_to_zero takes a list of integers as an input.
it returns True if there are two distinct elements in the list that
sum to zero, and False otherwise.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/43. Retained base cases 9. Retained extended cases 974.

## HumanEval/44

Change numerical base of input number x to base.
return string representation after the conversion.
base numbers are less than 10.

Arguments are provided in this order (x, base). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/44. Retained base cases 12. Retained extended cases 466.

## HumanEval/46

The Fib4 number sequence is a sequence similar to the Fibbonacci sequnece that's defined as follows:
fib4(0) -> 0
fib4(1) -> 0
fib4(2) -> 2
fib4(3) -> 0
fib4(n) -> fib4(n-1) + fib4(n-2) + fib4(n-3) + fib4(n-4).
Please write a function to efficiently compute the n-th element of the fib4 number sequence.  Do not use recursion.
Four-term recurrence with initial values 0, 0, 2, 0.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/46. Retained base cases 4. Retained extended cases 132.

## HumanEval/48

Checks if given string is a palindrome

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/48. Retained base cases 7. Retained extended cases 989.

## HumanEval/49

Return 2^n modulo p (be aware of numerics).

Arguments are provided in this order (n, p). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/49. Retained base cases 7. Retained extended cases 983.

## HumanEval/51

remove_vowels is a function that takes string and returns string without vowels.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/51. Retained base cases 7. Retained extended cases 997.

## HumanEval/54

Check if two words have the same characters.

Arguments are provided in this order (s0, s1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/54. Retained base cases 7. Retained extended cases 999.

## HumanEval/55

Return n-th Fibonacci number.
Fibonacci value with F(0)=0 and F(1)=1, checked by fast doubling.
The ordinal is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/55. Retained base cases 5. Retained extended cases 43.

## HumanEval/57

Return True is list elements are monotonically increasing or decreasing.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/57. Retained base cases 8. Retained extended cases 971.

## HumanEval/58

Return sorted unique common elements for two lists.

Arguments are provided in this order (l1, l2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task HumanEval/58. Retained base cases 4. Retained extended cases 985.

## HumanEval/59

Return the largest prime factor of n. Assume n > 1 and is not a prime.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/59. Retained base cases 5. Retained extended cases 174.

## HumanEval/60

sum_to_n is a function that sums numbers from 1 to n.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/60. Retained base cases 5. Retained extended cases 159.

## HumanEval/62

xs represent coefficients of a polynomial.
xs[0] + xs[1] * x + xs[2] * x^2 + ....
 Return derivative of this polynomial in the same form.

Arguments are provided in this order (xs). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task HumanEval/62. Retained base cases 5. Retained extended cases 948.

## HumanEval/63

The FibFib number sequence is a sequence similar to the Fibbonacci sequnece that's defined as follows:
fibfib(0) == 0
fibfib(1) == 0
fibfib(2) == 1
fibfib(n) == fibfib(n-1) + fibfib(n-2) + fibfib(n-3).
Please write a function to efficiently compute the n-th element of the fibfib number sequence.
Three-term recurrence with initial values 0, 0, 1.
The ordinal is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/63. Retained base cases 7. Retained extended cases 61.

## HumanEval/64

Write a function vowels_count which takes a string representing
a word as input and returns the number of vowels in the string.
Vowels in this case are 'a', 'e', 'i', 'o', 'u'. Here, 'y' is also a
vowel, but only when it is at the end of the given word.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/64. Retained base cases 7. Retained extended cases 992.

## HumanEval/67

In this task, you will be given a string that represents a number of apples and oranges 
that are distributed in a basket of fruit this basket contains 
apples, oranges, and mango fruits. Given the string that represents the total number of 
the oranges and apples and an integer that represent the total number of the fruits 
in the basket return the number of the mango fruits in the basket.
for examble:
fruit_distribution("5 apples and 6 oranges", 19) ->19 - 5 - 6 = 8
fruit_distribution("0 apples and 1 oranges",3) -> 3 - 0 - 1 = 2
fruit_distribution("2 apples and 3 oranges", 100) -> 100 - 2 - 3 = 95
fruit_distribution("100 apples and 1 oranges",120) -> 120 - 100 - 1 = 19

Arguments are provided in this order (s, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/67. Retained base cases 7. Retained extended cases 341.

## HumanEval/68

"Given an array representing a branch of a tree that has non-negative integer nodes
your task is to pluck one of the nodes and return it.
The plucked node should be the node with the smallest even value.
If multiple nodes with the same smallest even value are found return the node that has smallest index.

The plucked node should be returned in a list, [ smalest_value, its index ],
If there are no even values or the given array is empty, return [].

Example 1:
    Input: [4,2,3]
    Output: [2, 1]
    Explanation: 2 has the smallest even value, and 2 has the smallest index.

Example 2:
    Input: [1,2,3]
    Output: [2, 1]
    Explanation: 2 has the smallest even value, and 2 has the smallest index. 

Example 3:
    Input: []
    Output: []

Example 4:
    Input: [5, 0, 3, 0, 4, 2]
    Output: [0, 1]
    Explanation: 0 is the smallest value, but  there are two zeros,
                 so we will choose the first zero, which has the smallest index.

Constraints:
    * 1 <= nodes.length <= 10000
    * 0 <= node.value

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/68. Retained base cases 8. Retained extended cases 1000.

## HumanEval/70

Given list of integers, return list in strange order.
Strange sorting, is when you start with the minimum value,
then maximum of the remaining integers, then minimum and so on.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/70. Retained base cases 9. Retained extended cases 975.

## HumanEval/72

Write a function that returns True if the object q will fly, and False otherwise.
The object q will fly if it's balanced (it is a palindromic list) and the sum of its elements is less than or equal the maximum possible weight w.

Arguments are provided in this order (q, w). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/72. Retained base cases 6. Retained extended cases 691.

## HumanEval/73

Given an array arr of integers, find the minimum number of elements that
need to be changed to make the array palindromic. A palindromic array is an array that
is read the same backwards and forwards. In one change, you can change one element to any other element.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/73. Retained base cases 8. Retained extended cases 962.

## HumanEval/75

Write a function that returns true if the given number is the multiplication of 3 prime numbers
and false otherwise.
Knowing that (a) is less then 100.

Arguments are provided in this order (a). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/75. Retained base cases 4. Retained extended cases 93.

## HumanEval/78

You have been tasked to write a function that receives 
a hexadecimal number as a string and counts the number of hexadecimal 
digits that are primes (prime number, or a prime, is a natural number 
greater than 1 that is not a product of two smaller natural numbers).
Hexadecimal digits are 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, A, B, C, D, E, F.
Prime numbers are 2, 3, 5, 7, 11, 13, 17,...
So you have to determine a number of the following digits: 2, 3, 5, 7, 
B (=decimal 11), D (=decimal 13).
Note: you may assume the input is always correct or empty string, 
and symbols A,B,C,D,E,F are always uppercase.

Arguments are provided in this order (num). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/78. Retained base cases 13. Retained extended cases 1000.

## HumanEval/82

Write a function that takes a string and returns True if the string
length is a prime number or False otherwise
Examples
prime_length('Hello') == True
prime_length('abcdcba') == True
prime_length('kittens') == True
prime_length('orange') == False

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/82. Retained base cases 16. Retained extended cases 962.

## HumanEval/83

Given a positive integer n, return the count of the numbers of n-digit
positive integers that start or end with 1.
Inclusion-exclusion for n-digit integers starting or ending in 1.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Return the exact count as a decimal digit string without leading zeros.

Source task HumanEval/83. Retained base cases 5. Retained extended cases 104.

## HumanEval/84

Given a positive integer N, return the total sum of its digits in binary.

Example
    For N = 1000, the sum of digits will be 1 the output should be "1".
    For N = 150, the sum of digits will be 6 the output should be "110".
    For N = 147, the sum of digits will be 12 the output should be "1100".

Variables:
    @N integer
         Constraints: 0 ≤ N ≤ 10000.
Output:
     a string of binary number

Arguments are provided in this order (N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/84. Retained base cases 5. Retained extended cases 211.

## HumanEval/85

Given a non-empty list of integers lst. add the even elements that are at odd indices..

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/85. Retained base cases 4. Retained extended cases 994.

## HumanEval/86

Write a function that takes a string and returns an ordered version of it.
Ordered version of string, is a string where all words (separated by space)
are replaced by a new word where all the characters arranged in
ascending order based on ascii value.
Note: You should keep the order of words and blank spaces in the sentence.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/86. Retained base cases 7. Retained extended cases 1000.

## HumanEval/87

You are given a 2 dimensional data, as a nested lists,
which is similar to matrix, however, unlike matrices,
each row may contain a different number of columns.
Given lst, and integer x, find integers x in the list,
and return list of tuples, [(x1, y1), (x2, y2) ...] such that
each tuple is a coordinate - (row, columns), starting with 0.
Sort coordinates initially by rows in ascending order.
Also, sort coordinates of the row by columns in descending order.

Arguments are provided in this order (lst, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/87. Retained base cases 6. Retained extended cases 207.

## HumanEval/89

Create a function encrypt that takes a string as an argument and
returns a string encrypted with the alphabet being rotated. 
The alphabet should be rotated in a manner such that the letters 
shift down by two multiplied to two places.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/89. Retained base cases 8. Retained extended cases 1000.

## HumanEval/91

You'll be given a string of words, and your task is to count the number
of boredoms. A boredom is a sentence that starts with the word "I".
Sentences are delimited by '.', '?' or '!'.

Arguments are provided in this order (S). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/91. Retained base cases 6. Retained extended cases 1000.

## HumanEval/93

Write a function that takes a message, and encodes in such a 
way that it swaps case of all letters, replaces all vowels in 
the message with the letter that appears 2 places ahead of that 
vowel in the english alphabet. 
Assume only letters.

Arguments are provided in this order (message). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/93. Retained base cases 5. Retained extended cases 1000.

## HumanEval/95

Given a dictionary, return True if all keys are strings in lower 
case or all keys are strings in upper case, else return False.
The function should return False is the given dictionary is empty.

Arguments are provided in this order (dict). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task HumanEval/95. Retained base cases 14. Retained extended cases 510.

## HumanEval/96

Implement a function that takes an non-negative integer and returns an array of the first n
integers that are prime numbers and less than n.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/96. Retained base cases 10. Retained extended cases 180.

## HumanEval/97

Complete the function that takes two integers and returns 
the product of their unit digits.
Assume the input is always valid.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/97. Retained base cases 16. Retained extended cases 969.

## HumanEval/99-exact

Round a finite decimal string to the nearest integer, taking the written decimal value exactly and rounding half ties away from zero.

Return an exact JavaScript BigInt. The argument is a string.

Source task HumanEval/99. Retained base cases 5. Retained extended cases 710.

## HumanEval/100

Given a positive integer n, you have to make a pile of n levels of stones.
The first level has n stones.
The number of stones in the next level is:
    - the next odd number if n is odd.
    - the next even number if n is even.
Return the number of stones in each level in a list, where element at index
i represents the number of stones in the level (i+1).

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/100. Retained base cases 5. Retained extended cases 112.

## HumanEval/101

You will be given a string of words separated by commas or spaces. Your task is
to split the string into words and return an array of the words.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/101. Retained base cases 6. Retained extended cases 1000.

## HumanEval/102

This function takes two positive numbers x and y and returns the
biggest even integer number that is in the range [x, y] inclusive. If 
there's no such number, then the function should return -1.

Arguments are provided in this order (x, y). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/102. Retained base cases 8. Retained extended cases 944.

## HumanEval/103

You are given two positive integers n and m, and your task is to compute the
average of the integers from n through m (including n and m). 
Round the answer to the nearest integer and convert that to binary.
If n is greater than m, return -1.

Arguments are provided in this order (n, m). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/103. Retained base cases 12. Retained extended cases 939.

## HumanEval/104

Given a list of positive integers x. return a sorted list of all 
elements that hasn't any even digit.

Note: Returned list should be sorted in increasing order.

Arguments are provided in this order (x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/104. Retained base cases 4. Retained extended cases 999.

## HumanEval/105

Given an array of integers, sort the integers that are between 1 and 9 inclusive,
reverse the resulting array, and then replace each digit by its corresponding name from
"One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine".

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/105. Retained base cases 5. Retained extended cases 999.

## HumanEval/106

Implement the function f that takes n as a parameter,
and returns a list of size n, such that the value of the element at index i is the factorial of i if i is even
or the sum of numbers from 1 to i otherwise.
i starts from 1.
the factorial of i is the multiplication of the numbers from 1 to i (1 * 2 * ... * i).
One-based positions alternate triangular sums and factorials.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/106. Retained base cases 4. Retained extended cases 104.

## HumanEval/107

Given a positive integer n, return a tuple that has the number of even and odd
integer palindromes that fall within the range(1, n), inclusive.

Example 1:

    Input: 3
    Output: (1, 2)
    Explanation:
    Integer palindrome are 1, 2, 3. one of them is even, and two of them are odd.

Example 2:

    Input: 12
    Output: (4, 6)
    Explanation:
    Integer palindrome are 1, 2, 3, 4, 5, 6, 7, 8, 9, 11. four of them are even, and 6 of them are odd.

Note:
    1. 1 <= n <= 10^3
    2. returned tuple has the number of even and odd integer palindromes respectively.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/107. Retained base cases 8. Retained extended cases 169.

## HumanEval/109

We have an array 'arr' of N integers arr[1], arr[2], ..., arr[N].The
numbers in the array will be randomly ordered. Your task is to determine if
it is possible to get an array sorted in non-decreasing order by performing 
the following operation on the given array:
    You are allowed to perform right shift operation any number of times.

One right shift operation means shifting all elements of the array by one
position in the right direction. The last element of the array will be moved to
the starting position in the array i.e. 0th index. 

If it is possible to obtain the sorted array by performing the above operation
then return True else return False.
If the given array is empty then return True.

Note: The given list is guaranteed to have unique elements.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/109. Retained base cases 5. Retained extended cases 953.

## HumanEval/110

In this problem, you will implement a function that takes two lists of numbers,
and determines whether it is possible to perform an exchange of elements
between them to make lst1 a list of only even numbers.
There is no limit on the number of exchanged elements between lst1 and lst2.
If it is possible to exchange elements between the lst1 and lst2 to make
all the elements of lst1 to be even, return "YES".
Otherwise, return "NO".

Arguments are provided in this order (lst1, lst2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/110. Retained base cases 7. Retained extended cases 1000.

## HumanEval/111

Given a string representing a space separated lowercase letters, return a dictionary
of the letter with the most repetition and containing the corresponding count.
If several letters have the same occurrence, return all of them.

Arguments are provided in this order (test). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/111. Retained base cases 8. Retained extended cases 655.

## HumanEval/112

Task
We are given two strings s and c, you have to deleted all the characters in s that are equal to any character in c
then check if the result string is palindrome.
A string is called palindrome if it reads the same backward as forward.
You should return a tuple containing the result string and True/False for the check.
Example
For s = "abcde", c = "ae", the result should be ('bcd',False)
For s = "abcdef", c = "b"  the result should be ('acdef',False)
For s = "abcdedcba", c = "ab", the result should be ('cdedc',True)

Arguments are provided in this order (s, c). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/112. Retained base cases 9. Retained extended cases 997.

## HumanEval/113

Given a list of strings, where each string consists of only digits, return a list.
Each element i of the output should be "the number of odd elements in the
string i of the input." where all the i's should be replaced by the number
of odd digits in the i'th string of the input.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/113. Retained base cases 3. Retained extended cases 983.

## HumanEval/115

You are given a rectangular grid of wells. Each row represents a single well,
and each 1 in a row represents a single unit of water.
Each well has a corresponding bucket that can be used to extract water from it, 
and all buckets have the same capacity.
Your task is to use the buckets to empty the wells.
Output the number of times you need to lower the buckets.

Example 1:
    Input: 
        grid : [[0,0,1,0], [0,1,0,0], [1,1,1,1]]
        bucket_capacity : 1
    Output: 6

Example 2:
    Input: 
        grid : [[0,0,1,1], [0,0,0,0], [1,1,1,1], [0,1,1,1]]
        bucket_capacity : 2
    Output: 5

Example 3:
    Input: 
        grid : [[0,0,0], [0,0,0]]
        bucket_capacity : 5
    Output: 0

Constraints:
    * all wells have the same length
    * 1 <= grid.length <= 10^2
    * 1 <= grid[:,1].length <= 10^2
    * grid[i][j] -> 0 | 1
    * 1 <= capacity <= 10

Arguments are provided in this order (grid, capacity). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/115. Retained base cases 5. Retained extended cases 801.

## HumanEval/116

In this Kata, you have to sort an array of non-negative integers according to
number of ones in their binary representation in ascending order.
For similar number of ones, sort based on decimal value.

It must be implemented like this:

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/116. Retained base cases 8. Retained extended cases 722.

## HumanEval/117

Given a string s and a natural number n, you have been tasked to implement 
a function that returns a list of all words from string s that contain exactly 
n consonants, in order these words appear in the string s.
If the string s is empty then the function should return an empty list.
Note: you may assume the input string contains only letters and spaces.

Arguments are provided in this order (s, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/117. Retained base cases 14. Retained extended cases 1000.

## HumanEval/119

You are given a list of two strings, both strings consist of open
parentheses '(' or close parentheses ')' only.
Your job is to check if it is possible to concatenate the two strings in
some order, that the resulting string will be good.
A string S is considered to be good if and only if all parentheses in S
are balanced. For example: the string '(())()' is good, while the string
'())' is not.
Return 'Yes' if there's a way to make a good string, and return 'No' otherwise.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/119. Retained base cases 12. Retained extended cases 648.

## HumanEval/120

Given an array arr of integers and a positive integer k, return a sorted list 
of length k with the maximum k numbers in arr.

Example 1:

    Input: arr = [-3, -4, 5], k = 3
    Output: [-4, -3, 5]

Example 2:

    Input: arr = [4, -4, 4], k = 2
    Output: [4, 4]

Example 3:

    Input: arr = [-3, 2, 1, 2, -1, -2, 1], k = 1
    Output: [2]

Note:
    1. The length of the array will be in the range of [1, 1000].
    2. The elements in the array will be in the range of [-1000, 1000].
    3. 0 <= k <= len(arr)

Arguments are provided in this order (arr, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/120. Retained base cases 11. Retained extended cases 1000.

## HumanEval/121

Given a non-empty list of integers, return the sum of all of the odd elements that are in even positions.


Examples
solution([5, 8, 7, 1]) ==> 12
solution([3, 3, 3, 3, 3]) ==> 9
solution([30, 13, 24, 321]) ==>0

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/121. Retained base cases 7. Retained extended cases 998.

## HumanEval/122

Given a non-empty array of integers arr and an integer k, return
the sum of the elements with at most two digits from the first k elements of arr.

Constraints:
    1. 1 <= len(arr) <= 100
    2. 1 <= k <= len(arr)

Arguments are provided in this order (arr, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/122. Retained base cases 5. Retained extended cases 1000.

## HumanEval/124

You have to write a function which validates a given date string and
returns True if the date is valid otherwise False.
The date is valid if all of the following rules are satisfied:
1. The date string is not empty.
2. The number of days is not less than 1 or higher than 31 days for months 1,3,5,7,8,10,12. And the number of days is not less than 1 or higher than 30 days for months 4,6,9,11. And, the number of days is not less than 1 or higher than 29 for the month 2.
3. The months should not be less than 1 or higher than 12.
4. The date should be in the format: mm-dd-yyyy

Arguments are provided in this order (date). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/124. Retained base cases 16. Retained extended cases 985.

## HumanEval/125

Given a string of words, return a list of words split on whitespace, if no whitespaces exists in the text you
should split on commas ',' if no commas exists you should return the number of lower-case letters with odd order in the
alphabet, ord('a') = 0, ord('b') = 1, ... ord('z') = 25
Examples
split_words("Hello world!") ➞ ["Hello", "world!"]
split_words("Hello,world!") ➞ ["Hello", "world!"]
split_words("abcdef") == 3

Arguments are provided in this order (txt). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/125. Retained base cases 8. Retained extended cases 804.

## HumanEval/126

Given a list of numbers, return whether or not they are sorted
in ascending order. If list has more than 1 duplicate of the same
number, return False. Assume no negative numbers and only integers.

Examples
is_sorted([5]) ➞ True
is_sorted([1, 2, 3, 4, 5]) ➞ True
is_sorted([1, 3, 2, 4, 5]) ➞ False
is_sorted([1, 2, 3, 4, 5, 6]) ➞ True
is_sorted([1, 2, 3, 4, 5, 6, 7]) ➞ True
is_sorted([1, 3, 2, 4, 5, 6, 7]) ➞ False
is_sorted([1, 2, 2, 3, 3, 4]) ➞ True
is_sorted([1, 2, 2, 2, 3, 4]) ➞ False

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/126. Retained base cases 13. Retained extended cases 999.

## HumanEval/127

You are given two intervals,
where each interval is a pair of integers. For example, interval = (start, end) = (1, 2).
The given intervals are closed which means that the interval (start, end)
includes both start and end.
For each given interval, it is assumed that its start is less or equal its end.
Your task is to determine whether the length of intersection of these two 
intervals is a prime number.
Example, the intersection of the intervals (1, 3), (2, 4) is (2, 3)
which its length is 1, which not a prime number.
If the length of the intersection is a prime number, return "YES",
otherwise, return "NO".
If the two intervals don't intersect, return "NO".


[input/output] samples:
intersection((1, 2), (2, 3)) ==> "NO"
intersection((-1, 1), (0, 4)) ==> "NO"
intersection((-3, -1), (-5, 5)) ==> "YES"

Arguments are provided in this order (interval1, interval2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/127. Retained base cases 8. Retained extended cases 580.

## HumanEval/129

Given a grid with N rows and N columns (N >= 2) and a positive integer k, 
each cell of the grid contains a value. Every integer in the range [1, N * N]
inclusive appears exactly once on the cells of the grid.

You have to find the minimum path of length k in the grid. You can start
from any cell, and in each step you can move to any of the neighbor cells,
in other words, you can go to cells which share an edge with you current
cell.
Please note that a path of length k means visiting exactly k cells (not
necessarily distinct).
You CANNOT go off the grid.
A path A (of length k) is considered less than a path B (of length k) if
after making the ordered lists of the values on the cells that A and B go
through (let's call them lst_A and lst_B), lst_A is lexicographically less
than lst_B, in other words, there exist an integer index i (1 <= i <= k)
such that lst_A[i] < lst_B[i] and for any j (1 <= j < i) we have
lst_A[j] = lst_B[j].
It is guaranteed that the answer is unique.
Return an ordered list of the values on the cells that the minimum path go through.

Arguments are provided in this order (grid, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/129. Retained base cases 10. Retained extended cases 189.

## HumanEval/133

You are given a list of numbers.
You need to return the sum of squared numbers in the given list,
round each element in the list to the upper int(Ceiling) first.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/133. Retained base cases 12. Retained extended cases 998.

## HumanEval/134

Create a function that returns True if the last character
of a given string is an alphabetical character and is not
a part of a word, and False otherwise.
Note: "word" is a group of characters separated by space.

Arguments are provided in this order (txt). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/134. Retained base cases 10. Retained extended cases 991.

## HumanEval/135

Create a function which returns the largest index of an element which
is not greater than or equal to the element immediately preceding it. If
no such element exists then return -1. The given array will not contain
duplicate values.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/135. Retained base cases 5. Retained extended cases 970.

## HumanEval/136

Create a function that returns a tuple (a, b), where 'a' is
the largest of negative integers, and 'b' is the smallest
of positive integers in a list.
If there is no negative or positive integers, return them as None.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/136. Retained base cases 11. Retained extended cases 998.

## HumanEval/138

Evaluate whether the given number n can be written as the sum of exactly 4 positive even numbers
Example
is_equal_to_sum_even(4) == False
is_equal_to_sum_even(6) == False
is_equal_to_sum_even(8) == True

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/138. Retained base cases 8. Retained extended cases 113.

## HumanEval/139

The Brazilian factorial is defined as:
brazilian_factorial(n) = n! * (n-1)! * (n-2)! * ... * 1!
where n > 0
Product of factorials from 1 through positive n.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/139. Retained base cases 4. Retained extended cases 127.

## HumanEval/140

Given a string text, replace all spaces in it with underscores, 
and if a string has more than 2 consecutive spaces, 
then replace all consecutive spaces with - 

fix_spaces("Example") == "Example"
fix_spaces("Example 1") == "Example_1"
fix_spaces(" Example 2") == "_Example_2"
fix_spaces(" Example   3") == "_Example-3"

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/140. Retained base cases 5. Retained extended cases 1000.

## HumanEval/141

Create a function which takes a string representing a file's name, and returns
'Yes' if the the file's name is valid, and returns 'No' otherwise.
A file's name is considered to be valid if and only if all the following conditions 
are met:
- There should not be more than three digits ('0'-'9') in the file's name.
- The file's name contains exactly one dot '.'
- The substring before the dot should not be empty, and it starts with a letter from 
the latin alphapet ('a'-'z' and 'A'-'Z').
- The substring after the dot should be one of these: ['txt', 'exe', 'dll']

Arguments are provided in this order (file_name). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/141. Retained base cases 26. Retained extended cases 1000.

## HumanEval/142

"
This function will take a list of integers. For all entries in the list, the function shall square the integer entry if its index is a 
multiple of 3 and will cube the integer entry if its index is a multiple of 4 and not a multiple of 3. The function will not 
change the entries in the list whose indexes are not a multiple of 3 or 4. The function shall then return the sum of all entries.
Zero-based index test gives the square rule precedence over cubing.

Arguments are provided in this order (lst). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/142. Retained base cases 11. Retained extended cases 997.

## HumanEval/143

You are given a string representing a sentence,
the sentence contains some words separated by a space,
and you have to return a string that contains the words from the original sentence,
whose lengths are prime numbers,
the order of the words in the new string should be the same as the original one.

Example 1:
    Input: sentence = "This is a test"
    Output: "is"

Example 2:
    Input: sentence = "lets go for swimming"
    Output: "go for"

Constraints:
    * 1 <= len(sentence) <= 100
    * sentence contains only letters

Arguments are provided in this order (sentence). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/143. Retained base cases 7. Retained extended cases 1000.

## HumanEval/144

Your task is to implement a function that will simplify the expression
x * n. The function returns True if x * n evaluates to a whole number and False
otherwise. Both x and n, are string representation of a fraction, and have the following format,
<numerator>/<denominator> where both numerator and denominator are positive whole numbers.

You can assume that x, and n are valid fractions, and do not have zero as denominator.

simplify("1/5", "5/1") = True
simplify("1/6", "2/1") = False
simplify("7/10", "10/2") = False

Arguments are provided in this order (x, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/144. Retained base cases 13. Retained extended cases 998.

## HumanEval/145

Write a function which sorts the given list of integers
in ascending order according to the sum of their digits.
Note: if there are several items with similar sum of their digits,
order them based on their index in original list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/145. Retained base cases 6. Retained extended cases 1000.

## HumanEval/146

Write a function that takes an array of numbers as input and returns 
the number of elements in the array that are greater than 10 and both 
first and last digits of a number are odd (1, 3, 5, 7, 9).

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/146. Retained base cases 7. Retained extended cases 988.

## HumanEval/147

You are given a positive integer n. You have to create an integer array a of length n.
    For each i (1 ≤ i ≤ n), the value of a[i] = i * i - i + 1.
    Return the number of triples (a[i], a[j], a[k]) of a where i < j < k, 
and a[i] + a[j] + a[k] is a multiple of 3.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/147. Retained base cases 4. Retained extended cases 115.

## HumanEval/148

There are eight planets in our solar system: the closerst to the Sun 
is Mercury, the next one is Venus, then Earth, Mars, Jupiter, Saturn, 
Uranus, Neptune.
Write a function that takes two planet names as strings planet1 and planet2. 
The function should return a tuple containing all planets whose orbits are 
located between the orbit of planet1 and the orbit of planet2, sorted by 
the proximity to the sun. 
The function should return an empty tuple if planet1 or planet2
are not correct planet names. 
Examples
bf("Jupiter", "Neptune") ==> ("Saturn", "Uranus")
bf("Earth", "Mercury") ==> ("Venus")
bf("Mercury", "Uranus") ==> ("Venus", "Earth", "Mars", "Jupiter", "Saturn")

Arguments are provided in this order (planet1, planet2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/148. Retained base cases 11. Retained extended cases 971.

## HumanEval/149

Write a function that accepts a list of strings as a parameter,
deletes the strings that have odd lengths from it,
and returns the resulted list with a sorted order,
The list is always a list of strings and never an array of numbers,
and it may contain duplicates.
The order of the list should be ascending by length of each word, and you
should return the list sorted by that rule.
If two words have the same length, sort the list alphabetically.
The function should return a list of strings in sorted order.
You may assume that all words will have the same length.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/149. Retained base cases 7. Retained extended cases 979.

## HumanEval/150

A simple program which should return the value of x if n is 
a prime number and should return the value of y otherwise.

Arguments are provided in this order (n, x, y). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/150. Retained base cases 10. Retained extended cases 998.

## HumanEval/151

Given a list of numbers, return the sum of squares of the numbers
in the list that are odd. Ignore numbers that are negative or not integers.

double_the_difference([1, 3, 2, 0]) == 1 + 9 + 0 + 0 = 10
double_the_difference([-1, -2, 0]) == 0
double_the_difference([9, -2]) == 81
double_the_difference([0]) == 0  

If the input list is empty, return 0.

Arguments are provided in this order (lst). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/151. Retained base cases 7. Retained extended cases 999.

## HumanEval/152

I think we all remember that feeling when the result of some long-awaited
event is finally known. The feelings and thoughts you have at that moment are
definitely worth noting down and comparing.
Your task is to determine if a person correctly guessed the results of a number of matches.
You are given two arrays of scores and guesses of equal length, where each index shows a match. 
Return an array of the same length denoting how far off each guess was. If they have guessed correctly,
the value is 0, and if not, the value is the absolute difference between the guess and the score.

Arguments are provided in this order (game, guess). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/152. Retained base cases 4. Retained extended cases 1000.

## HumanEval/153

You will be given the name of a class (a string) and a list of extensions.
The extensions are to be used to load additional classes to the class. The
strength of the extension is as follows: Let CAP be the number of the uppercase
letters in the extension's name, and let SM be the number of lowercase letters 
in the extension's name, the strength is given by the fraction CAP - SM. 
You should find the strongest extension and return a string in this 
format: ClassName.StrongestExtensionName.
If there are two or more extensions with the same strength, you should
choose the one that comes first in the list.
For example, if you are given "Slices" as the class and a list of the
extensions: ['SErviNGSliCes', 'Cheese', 'StuFfed'] then you should
return 'Slices.SErviNGSliCes' since 'SErviNGSliCes' is the strongest extension 
(its strength is -1).

Arguments are provided in this order (class_name, extensions). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/153. Retained base cases 9. Retained extended cases 194.

## HumanEval/156

Given a positive integer, obtain its roman numeral equivalent as a string,
and return it in lowercase.
Restrictions: 1 <= num <= 1000

Arguments are provided in this order (number). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/156. Retained base cases 14. Retained extended cases 206.

## HumanEval/157

Given the lengths of the three sides of a triangle. Return True if the three
sides form a right-angled triangle, False otherwise.
A right-angled triangle is a triangle in which one angle is right angle or 
90 degree.

Arguments are provided in this order (a, b, c). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/157. Retained base cases 11. Retained extended cases 1000.

## HumanEval/158

Write a function that accepts a list of strings.
The list contains different words. Return the word with maximum number
of unique characters. If multiple strings have maximum number of unique
characters, return the one which comes first in lexicographical order.

find_max(["name", "of", "string"]) == "string"
find_max(["name", "enam", "game"]) == "enam"
find_max(["aaaaaaa", "bb" ,"cc"]) == ""aaaaaaa"

Arguments are provided in this order (words). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/158. Retained base cases 10. Retained extended cases 897.

## HumanEval/159

You're a hungry rabbit, and you already have eaten a certain number of carrots,
but now you need to eat more carrots to complete the day's meals.
you should return an array of [ total number of eaten carrots after your meals,
                                the number of carrots left after your meals ]
if there are not enough remaining carrots, you will eat all remaining carrots, but will still be hungry.

Arguments are provided in this order (number, need, remaining). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/159. Retained base cases 6. Retained extended cases 976.

## HumanEval/160

Given two lists operator, and operand. The first list has basic algebra operations, and 
the second list is a list of integers. Use the two given lists to build the algebric 
expression and return the evaluation of this expression.

The basic algebra operations:
Addition ( + ) 
Subtraction ( - ) 
Multiplication ( * ) 
Floor division ( // ) 
Exponentiation ( ** ) 

Note:
    The length of operator list is equal to the length of operand list minus one.
    Operand is a list of of non-negative integers.
    Operator list has at least one operator, and operand list has at least two operands.
Allowed arithmetic and precedence on the stated nonnegative integer operands.

Arguments are provided in this order (operator, operand). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task HumanEval/160. Retained base cases 3. Retained extended cases 449.

## HumanEval/163

Given two positive integers a and b, return the even digits between a
and b, in ascending order.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task HumanEval/163. Retained base cases 4. Retained extended cases 982.

## Mbpp/3

Write a JavaScript function to identify non-prime numbers.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/3. Retained base cases 5. Retained extended cases 103.

## Mbpp/4

Write a function to find the n largest integers from a given list of numbers, returned in descending order.

Arguments are provided in this order (nums, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/4. Retained base cases 3. Retained extended cases 106.

## Mbpp/6

Write a JavaScript function to check whether the two numbers differ at one bit position only or not.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/6. Retained base cases 6. Retained extended cases 108.

## Mbpp/8

Write a function to find squares of individual elements in a list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/8. Retained base cases 3. Retained extended cases 103.

## Mbpp/9

Write a JavaScript function to find the minimum number of rotations (greater than 0) required to get the same string.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/9. Retained base cases 3. Retained extended cases 101.

## Mbpp/11

Write a JavaScript function to remove first and last occurrence of a given character from the string.

Arguments are provided in this order (s, ch). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/11. Retained base cases 3. Retained extended cases 103.

## Mbpp/12

Write a function to sort a given matrix in ascending order according to the sum of its rows.

Arguments are provided in this order (M). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/12. Retained base cases 3. Retained extended cases 106.

## Mbpp/14

Write a JavaScript function to find the volume of a triangular prism.
Triangular prism volume from nonnegative length, base and height.

Arguments are provided in this order (l, b, h). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/14. Retained base cases 3. Retained extended cases 108.

## Mbpp/16

Write a function to that returns true if the input string contains sequences of lowercase letters joined with an underscore and false otherwise.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/16. Retained base cases 3. Retained extended cases 113.

## Mbpp/17

Write a function that returns the perimeter of a square given its side length as input.
Square perimeter equals four times its nonnegative side.
The side is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (a). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/17. Retained base cases 3. Retained extended cases 100.

## Mbpp/18

Write a function to remove characters from the first string which are present in the second string.

Arguments are provided in this order (string, second_string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/18. Retained base cases 3. Retained extended cases 104.

## Mbpp/19

Write a function to find whether a given array of integers contains any duplicate element.

Arguments are provided in this order (arraynums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/19. Retained base cases 3. Retained extended cases 102.

## Mbpp/20

Write a function to check if the given number is woodball or not.

Arguments are provided in this order (x). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/20. Retained base cases 3. Retained extended cases 101.

## Mbpp/56

Write a JavaScript function to check if a given number is one less than twice its reverse.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/56. Retained base cases 3. Retained extended cases 125.

## Mbpp/57

Write a JavaScript function to find the largest number that can be formed with the given list of digits.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/57. Retained base cases 3. Retained extended cases 102.

## Mbpp/58

Write a JavaScript function to check whether the given two integers have opposite sign or not.

Arguments are provided in this order (x, y). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/58. Retained base cases 4. Retained extended cases 105.

## Mbpp/59

Write a function to find the nth octagonal number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/59. Retained base cases 3. Retained extended cases 101.

## Mbpp/61

Write a JavaScript function to count the number of substrings with the sum of digits equal to their length.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/61. Retained base cases 3. Retained extended cases 102.

## Mbpp/62

Write a JavaScript function to find smallest number in a list.
Minimum member of the nonempty numeric list.

Arguments are provided in this order (xs). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/62. Retained base cases 3. Retained extended cases 101.

## Mbpp/63

Write a function to find the maximum difference between available pairs in the given tuple list.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/63. Retained base cases 3. Retained extended cases 121.

## Mbpp/64

Write a function to sort a list of tuples using the second value of each tuple.

Arguments are provided in this order (subjectmarks). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/64. Retained base cases 3. Retained extended cases 117.

## Mbpp/65

Write a function to flatten a list and sum all of its elements.
Sum after recursively flattening numeric lists.

Arguments are provided in this order (data_list). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/65. Retained base cases 3. Retained extended cases 112.

## Mbpp/66

Write a JavaScript function to count the number of positive numbers in a list.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/66. Retained base cases 3. Retained extended cases 107.

## Mbpp/68

Write a JavaScript function to check whether the given array is monotonic or not.

Arguments are provided in this order (A). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/68. Retained base cases 3. Retained extended cases 102.

## Mbpp/69

Write a function to check whether a list contains the given sublist or not.

Arguments are provided in this order (l, s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/69. Retained base cases 3. Retained extended cases 102.

## Mbpp/70

Write a function to find whether all the given tuples have equal length or not.

Arguments are provided in this order (Input). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/70. Retained base cases 3. Retained extended cases 118.

## Mbpp/71

Write a function to sort a list of elements.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/71. Retained base cases 3. Retained extended cases 108.

## Mbpp/72

Write a JavaScript function to check whether the given number can be represented as the difference of two squares or not.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/72. Retained base cases 3. Retained extended cases 104.

## Mbpp/74

Write a function to check whether it follows the sequence given in the patterns array.

Arguments are provided in this order (colors, patterns). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/74. Retained base cases 3. Retained extended cases 117.

## Mbpp/75

Write a function to find tuples which have all elements divisible by k from the given list of tuples.

Arguments are provided in this order (test_list, K). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/75. Retained base cases 3. Retained extended cases 106.

## Mbpp/79

Write a JavaScript function to check whether the length of the word is odd or not.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/79. Retained base cases 3. Retained extended cases 102.

## Mbpp/80

Write a function to find the nth tetrahedral number.
Nonnegative ordinal tetrahedral number from a binomial coefficient.
The ordinal is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/80. Retained base cases 3. Retained extended cases 99.

## Mbpp/84

Write a function to find the nth number in the newman conway sequence.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/84. Retained base cases 3. Retained extended cases 108.

## Mbpp/86

Write a function to find nth centered hexagonal number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/86. Retained base cases 3. Retained extended cases 101.

## Mbpp/87

Write a function to merge three dictionaries into a single dictionary.

Arguments are provided in this order (dict1, dict2, dict3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/87. Retained base cases 3. Retained extended cases 108.

## Mbpp/89

Write a function to find the closest smaller number than n.

Arguments are provided in this order (N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/89. Retained base cases 3. Retained extended cases 102.

## Mbpp/90

Write a JavaScript function to find the length of the longest word.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/90. Retained base cases 3. Retained extended cases 103.

## Mbpp/91

Write a function to check if a string is present as a substring in a given list of string values.

Arguments are provided in this order (str1, sub_str). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/91. Retained base cases 3. Retained extended cases 102.

## Mbpp/92

Write a function to check whether the given number is undulating or not.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/92. Retained base cases 3. Retained extended cases 101.

## Mbpp/93

Write a function to calculate the value of 'a' to the power 'b'.
Real scalar exponentiation over the released finite inputs.

Arguments are provided in this order (a, b). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/93. Retained base cases 3. Retained extended cases 110.

## Mbpp/94

Given a list of tuples, write a function that returns the first value of the tuple with the smallest second value.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/94. Retained base cases 3. Retained extended cases 106.

## Mbpp/95

Write a JavaScript function to find the length of the smallest list in a list of lists.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/95. Retained base cases 3. Retained extended cases 105.

## Mbpp/96

Write a JavaScript function to find the number of divisors of a given integer.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/96. Retained base cases 3. Retained extended cases 101.

## Mbpp/100

Write a function to find the next smallest palindrome of a specified integer, returned as an integer.

Arguments are provided in this order (num). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/100. Retained base cases 3. Retained extended cases 102.

## Mbpp/101

Write a function to find the kth element in the given array using 1-based indexing.

Arguments are provided in this order (arr, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/101. Retained base cases 3. Retained extended cases 104.

## Mbpp/102

Write a function to convert a snake case string to camel case string.

Arguments are provided in this order (word). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/102. Retained base cases 3. Retained extended cases 110.

## Mbpp/103

Write a function to find the Eulerian number a(n, m).

Arguments are provided in this order (n, m). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/103. Retained base cases 3. Retained extended cases 101.

## Mbpp/104

Write a function to sort each sublist of strings in a given list of lists.

Arguments are provided in this order (input_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/104. Retained base cases 3. Retained extended cases 121.

## Mbpp/105

Write a JavaScript function to count true booleans in the given list.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/105. Retained base cases 3. Retained extended cases 103.

## Mbpp/106

Write a function to append the given list to the given tuples.

Arguments are provided in this order (test_list, test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/106. Retained base cases 3. Retained extended cases 115.

## Mbpp/108

Write a function to merge three lists into a single sorted list.

Arguments are provided in this order (num1, num2, num3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/108. Retained base cases 3. Retained extended cases 118.

## Mbpp/109

Write a JavaScript function to find the number of numbers with an odd value when rotating a binary string the given number of times.

Arguments are provided in this order (s, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/109. Retained base cases 3. Retained extended cases 102.

## Mbpp/113

Write a function to check if a string represents an integer or not.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/113. Retained base cases 3. Retained extended cases 121.

## Mbpp/118

Write a function to convert a string to a list of strings split on the space character.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/118. Retained base cases 3. Retained extended cases 106.

## Mbpp/119

Write a JavaScript function to find the element that appears only once in a sorted array.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/119. Retained base cases 3. Retained extended cases 107.

## Mbpp/123

Write a function to sum all amicable numbers from 1 to a specified number.

Arguments are provided in this order (limit). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/123. Retained base cases 3. Retained extended cases 102.

## Mbpp/125

Write a function to find the maximum difference between the number of 0s and number of 1s in any sub-string of the given binary string.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/125. Retained base cases 3. Retained extended cases 102.

## Mbpp/126

Write a JavaScript function to find the sum of common divisors of two given numbers.
Exact sum of the divisors of the greatest common divisor.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/126. Retained base cases 3. Retained extended cases 107.

## Mbpp/128

Write a function to find words that are longer than n characters from a given list of words.

Arguments are provided in this order (n, s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/128. Retained base cases 3. Retained extended cases 104.

## Mbpp/129

Write a function to calculate whether the matrix is a magic square.

Arguments are provided in this order (my_matrix). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/129. Retained base cases 3. Retained extended cases 104.

## Mbpp/130

Write a function to find the item with maximum frequency in a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/130. Retained base cases 3. Retained extended cases 102.

## Mbpp/131

Write a JavaScript function to reverse only the vowels of a given string (where y is not a vowel).

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/131. Retained base cases 3. Retained extended cases 102.

## Mbpp/132

Write a function to convert a tuple to a string.

Arguments are provided in this order (tup1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/132. Retained base cases 3. Retained extended cases 102.

## Mbpp/133

Write a function to calculate the sum of the negative numbers of a given list of numbers.
Sum of strictly negative elements.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/133. Retained base cases 3. Retained extended cases 108.

## Mbpp/135

Write a function to find the nth hexagonal number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/135. Retained base cases 3. Retained extended cases 103.

## Mbpp/138

Write a JavaScript function to check whether the given number can be represented as sum of non-zero powers of 2 or not.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/138. Retained base cases 3. Retained extended cases 103.

## Mbpp/141

Write a function to sort a list of elements.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/141. Retained base cases 3. Retained extended cases 108.

## Mbpp/142

Write a function to count number items that are identical in the same position of three given lists.

Arguments are provided in this order (list1, list2, list3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/142. Retained base cases 3. Retained extended cases 110.

## Mbpp/145

Write a JavaScript function to find the maximum difference between any two elements in a given array.
Maximum absolute difference equals max minus min.
The input is a nonempty sequence of finite numeric values. Boolean elements are excluded.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/145. Retained base cases 3. Retained extended cases 105.

## Mbpp/161

Write a function to remove all elements from a given list present in another list.

Arguments are provided in this order (list1, list2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/161. Retained base cases 3. Retained extended cases 115.

## Mbpp/162

Write a function to calculate the sum (n - 2*i) from i=0 to n // 2, for instance n + (n-2) + (n-4)... (until n-x =< 0).

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/162. Retained base cases 4. Retained extended cases 105.

## Mbpp/165

Write a function to count the number of characters in a string that occur at the same position in the string as in the English alphabet (case insensitive).

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/165. Retained base cases 3. Retained extended cases 107.

## Mbpp/166

Write a function that counts the number of pairs of integers in a list that xor to an even number.

Arguments are provided in this order (A). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/166. Retained base cases 3. Retained extended cases 106.

## Mbpp/167

Write a JavaScript function to find the smallest power of 2 greater than or equal to n.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/167. Retained base cases 3. Retained extended cases 112.

## Mbpp/168

Write a function to count the number of occurrences of a number in a given list.

Arguments are provided in this order (a, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/168. Retained base cases 3. Retained extended cases 102.

## Mbpp/170

Write a function to find the sum of numbers in a list within a range specified by two indices.

Arguments are provided in this order (list1, m, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/170. Retained base cases 3. Retained extended cases 107.

## Mbpp/171

Write a function to find the perimeter of a regular pentagon from the length of its sides.
Regular pentagon perimeter equals five times the nonnegative side.
The side is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (a). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/171. Retained base cases 3. Retained extended cases 75.

## Mbpp/172

Write a function to count the number of occurence of the string 'std' in a given string.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/172. Retained base cases 5. Retained extended cases 101.

## Mbpp/222

Write a function to check if all the elements in tuple have same data type or not.

Arguments are provided in this order (test_tuple). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Tuples are records with a `$tuple` array. Lists are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/222. Retained base cases 3. Retained extended cases 128.

## Mbpp/223

Write a function that takes in a sorted array, its length (n), and an element and returns whether the element is the majority element in the given sorted array. (The majority element is the element that occurs more than n/2 times.)

Arguments are provided in this order (arr, n, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/223. Retained base cases 3. Retained extended cases 101.

## Mbpp/224

Write a JavaScript function to count the number of set bits (binary digits with value 1) in a given number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/224. Retained base cases 3. Retained extended cases 102.

## Mbpp/226

Write a JavaScript function to remove the characters which have odd index values of a given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/226. Retained base cases 4. Retained extended cases 103.

## Mbpp/227

Write a function to find minimum of three numbers.
Minimum of the three supplied numeric values.

Arguments are provided in this order (a, b, c). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/227. Retained base cases 3. Retained extended cases 105.

## Mbpp/230

Write a function that takes in a string and character, replaces blank spaces in the string with the character, and returns the string.

Arguments are provided in this order (str1, char). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/230. Retained base cases 3. Retained extended cases 104.

## Mbpp/234

Write a function to find the volume of a cube given its side length.
Cube volume from a nonnegative side.
The side is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/234. Retained base cases 3. Retained extended cases 100.

## Mbpp/235

Write a JavaScript function to set all even bits of a given number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/235. Retained base cases 3. Retained extended cases 102.

## Mbpp/238

Write a JavaScript function to count the number of non-empty substrings of a given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/238. Retained base cases 3. Retained extended cases 102.

## Mbpp/239

Write a function that takes in positive integers m and n and finds the number of possible sequences of length n, such that each element is a positive integer and is greater than or equal to twice the previous element but less than or equal to m.

Arguments are provided in this order (m, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/239. Retained base cases 3. Retained extended cases 104.

## Mbpp/240

Write a function that takes in two lists and replaces the last element of the first list with the elements of the second list.

Arguments are provided in this order (list1, list2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/240. Retained base cases 3. Retained extended cases 115.

## Mbpp/242

Write a function to count the total number of characters in a string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/242. Retained base cases 3. Retained extended cases 103.

## Mbpp/244

Write a JavaScript function to find the next perfect square greater than a given number.

Arguments are provided in this order (N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/244. Retained base cases 3. Retained extended cases 109.

## Mbpp/245

Write a function that takes an array and finds the maximum sum of a bitonic subsequence for the given array, where a sequence is bitonic if it is first increasing and then decreasing.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/245. Retained base cases 3. Retained extended cases 101.

## Mbpp/247

Write a function to find the length of the longest palindromic subsequence in the given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/247. Retained base cases 3. Retained extended cases 104.

## Mbpp/250

Write a JavaScript function that takes in a tuple and an element and counts the occcurences of the element in the tuple.

Arguments are provided in this order (tup, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/250. Retained base cases 3. Retained extended cases 112.

## Mbpp/251

Write a function that takes in a list and an element and inserts the element before each element in the list, and returns the resulting list.

Arguments are provided in this order (list1, element). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/251. Retained base cases 3. Retained extended cases 104.

## Mbpp/253

Write a JavaScript function that returns the number of integer elements in a given list.

Arguments are provided in this order (list1). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/253. Retained base cases 3. Retained extended cases 114.

## Mbpp/256

Write a JavaScript function that takes in a non-negative number and returns the number of prime numbers less than the given non-negative number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/256. Retained base cases 3. Retained extended cases 101.

## Mbpp/257

Write a function that takes in two numbers and returns a tuple with the second number and then the first number.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/257. Retained base cases 3. Retained extended cases 109.

## Mbpp/259

Write a function to maximize the given two tuples.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/259. Retained base cases 3. Retained extended cases 101.

## Mbpp/261

Write a function that takes in two tuples and performs mathematical division operation element-wise across the given tuples.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/261. Retained base cases 3. Retained extended cases 101.

## Mbpp/262

Write a function that takes in a list and an integer L and splits the given list into two parts where the length of the first part of the list is L, and returns the resulting lists in a tuple.

Arguments are provided in this order (list1, L). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/262. Retained base cases 3. Retained extended cases 109.

## Mbpp/264

Write a function to calculate a dog's age in dog's years.
For the first two years use 10.5 dog years per human year. For additional years use four dog years per human year.
Proposed explicit convention uses 10.5 per year for the first two years and 4 thereafter.
Human age is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (h_age). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/264. Retained base cases 3. Retained extended cases 101.

## Mbpp/265

Write a function that takes in a list and an integer n and splits a list for every nth element, returning a list of the resulting lists.

Arguments are provided in this order (S, step). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/265. Retained base cases 3. Retained extended cases 111.

## Mbpp/266

Write a function to find the lateral surface area of a cube given its side length.
Lateral surface covers four square faces of a cube.
The side is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/266. Retained base cases 3. Retained extended cases 103.

## Mbpp/267-exact

For a nonnegative integer n, return the exact sum of the squares of the first n positive odd integers.

Return an exact JavaScript BigInt. The argument is a BigInt.

Source task Mbpp/267. Retained base cases 3. Retained extended cases 118.

## Mbpp/268

Write a function to find the n'th star number.
Centered hexagram number at positive ordinal n.
The ordinal is a positive integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/268. Retained base cases 3. Retained extended cases 102.

## Mbpp/269

Write a function to find the ascii value of a character.

Arguments are provided in this order (k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/269. Retained base cases 3. Retained extended cases 82.

## Mbpp/270

Write a JavaScript function to find the sum of even numbers at even positions of a list.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/270. Retained base cases 3. Retained extended cases 105.

## Mbpp/271

Write a JavaScript function that takes in an integer n and finds the sum of the first n even natural numbers that are raised to the fifth power.
Exact sum of fifth powers of the first n positive even integers.
The count is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/271. Retained base cases 3. Retained extended cases 106.

## Mbpp/272

Write a function that takes in a list of tuples and returns a list containing the rear element of each tuple.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/272. Retained base cases 3. Retained extended cases 115.

## Mbpp/274

Write a JavaScript function that takes in a positive integer n and finds the sum of even index binomial coefficients.
Even-index binomial sum for the specified positive exponent.
The exponent is a positive integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/274. Retained base cases 3. Retained extended cases 102.

## Mbpp/277

Write a function that takes in a dictionary and integer n and filters the dictionary to only include entries with values greater than or equal to n.

Arguments are provided in this order (dict1, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/277. Retained base cases 3. Retained extended cases 106.

## Mbpp/278

Write a function to find the number of elements that occurs before the tuple element in the given tuple.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Tuples are records with a `$tuple` array. Lists are arrays.

Source task Mbpp/278. Retained base cases 3. Retained extended cases 121.

## Mbpp/280

Write a function that takes in an array and element and returns a tuple containing a boolean that indicates if the element is in the array and the index position of the element (or -1 if the element is not found).

Arguments are provided in this order (dlist, item). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/280. Retained base cases 3. Retained extended cases 108.

## Mbpp/281

Write a JavaScript function to check if the elements of a given list are unique or not.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/281. Retained base cases 3. Retained extended cases 103.

## Mbpp/282

Write a function to subtract two lists element-wise.

Arguments are provided in this order (nums1, nums2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/282. Retained base cases 3. Retained extended cases 104.

## Mbpp/283

Write a JavaScript function takes in an integer and check whether the frequency of each digit in the integer is less than or equal to the digit itself.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/283. Retained base cases 3. Retained extended cases 104.

## Mbpp/284

Write a function that takes in a list and element and checks whether all items in the list are equal to the given element.

Arguments are provided in this order (list1, element). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/284. Retained base cases 3. Retained extended cases 103.

## Mbpp/285

Write a function that checks whether a string contains the 'a' character followed by two or three 'b' characters.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/285. Retained base cases 3. Retained extended cases 101.

## Mbpp/286

Write a function to find the largest sum of a contiguous array in the modified array which is formed by repeating the given array k times.

Arguments are provided in this order (a, n, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/286. Retained base cases 3. Retained extended cases 102.

## Mbpp/287-exact

For a nonnegative integer n, return the exact sum of the squares of the first n positive even integers.

Return an exact JavaScript BigInt. The argument is a BigInt.

Source task Mbpp/287. Retained base cases 3. Retained extended cases 104.

## Mbpp/290

Write a function to find the list of maximum length in a list of lists.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/290. Retained base cases 3. Retained extended cases 109.

## Mbpp/292

Write a JavaScript function to find quotient of two numbers (rounded down to the nearest integer).

Arguments are provided in this order (n, m). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/292. Retained base cases 3. Retained extended cases 101.

## Mbpp/294

Write a function to find the maximum value in a given heterogeneous list.

Arguments are provided in this order (listval). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/294. Retained base cases 3. Retained extended cases 108.

## Mbpp/296

Write a JavaScript function to count inversions in an array.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/296. Retained base cases 3. Retained extended cases 106.

## Mbpp/297

Write a function to flatten a given nested list structure.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/297. Retained base cases 3. Retained extended cases 117.

## Mbpp/299

Write a function to calculate the maximum aggregate from the list of tuples.

Arguments are provided in this order (stdata). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/299. Retained base cases 3. Retained extended cases 105.

## Mbpp/305

Write a function to return two words from a list of words starting with letter 'p'.

Arguments are provided in this order (words). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/305. Retained base cases 3. Retained extended cases 107.

## Mbpp/306

Write a function to find the maximum sum of increasing subsequence from prefix until ith index and also including a given kth element which is after i, i.e., k > i .

Arguments are provided in this order (a, n, index, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/306. Retained base cases 3. Retained extended cases 101.

## Mbpp/308

Write a function to find the specified number of largest products from two given lists, selecting one factor from each list.

Arguments are provided in this order (nums1, nums2, N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/308. Retained base cases 3. Retained extended cases 101.

## Mbpp/310

Write a function to convert a given string to a tuple of characters.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/310. Retained base cases 3. Retained extended cases 113.

## Mbpp/311

Write a JavaScript function to set the left most unset bit.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/311. Retained base cases 3. Retained extended cases 109.

## Mbpp/388

Write a JavaScript function to find the highest power of 2 that is less than or equal to n.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/388. Retained base cases 3. Retained extended cases 103.

## Mbpp/389

Write a function to find the n'th lucas number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/389. Retained base cases 3. Retained extended cases 36.

## Mbpp/390

Write a function to apply a given format string to all of the elements in a list.

Arguments are provided in this order (list_, string). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/390. Retained base cases 3. Retained extended cases 105.

## Mbpp/391

Write a function to convert more than one list to nested dictionary.
Return one nested mapping for each position up to the shortest list. The first list supplies the outer key, the second the inner key, and the third the value.
Three lists form a list of nested mappings. The proposed contract specifies truncation to the shortest list.

Arguments are provided in this order (l1, l2, l3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/391. Retained base cases 3. Retained extended cases 104.

## Mbpp/392

Write a function to find the maximum sum possible by using the given equation f(n) = max( (f(n/2) + f(n/3) + f(n/4) + f(n/5)), n).

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/392. Retained base cases 3. Retained extended cases 106.

## Mbpp/394

Write a function to check if given tuple contains no duplicates.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/394. Retained base cases 3. Retained extended cases 49.

## Mbpp/398

Write a function to compute the sum of digits of each number of a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/398. Retained base cases 3. Retained extended cases 105.

## Mbpp/405

Write a function to check whether an element exists within a tuple.

Arguments are provided in this order (tuplex, element). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/405. Retained base cases 3. Retained extended cases 107.

## Mbpp/409

Write a function to find the minimum product from the pairs of tuples within a given list.
Minimum product across the given pairs.

Arguments are provided in this order (list1). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/409. Retained base cases 3. Retained extended cases 111.

## Mbpp/410

Write a function to find the minimum value in a given heterogeneous list.

Arguments are provided in this order (listval). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/410. Retained base cases 3. Retained extended cases 104.

## Mbpp/412

Write a JavaScript function to remove odd numbers from a given list.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/412. Retained base cases 3. Retained extended cases 109.

## Mbpp/413

Write a function to extract the nth element from a given list of tuples.

Arguments are provided in this order (list1, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/413. Retained base cases 3. Retained extended cases 105.

## Mbpp/414

Write a JavaScript function to check whether any value in a sequence exists in a sequence or not.

Arguments are provided in this order (list1, list2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/414. Retained base cases 3. Retained extended cases 104.

## Mbpp/415

Write a JavaScript function to find a pair with highest product from a given array of integers.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/415. Retained base cases 3. Retained extended cases 113.

## Mbpp/418

Write a JavaScript function to find the element of a list having maximum length.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/418. Retained base cases 3. Retained extended cases 110.

## Mbpp/419

Write a function to round every number of a given list of numbers and print the total sum multiplied by the length of the list.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/419. Retained base cases 3. Retained extended cases 107.

## Mbpp/420

Write a JavaScript function to find the cube sum of first n even natural numbers.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/420. Retained base cases 3. Retained extended cases 102.

## Mbpp/421

Write a function to concatenate each element of tuple by the delimiter.

Arguments are provided in this order (test_tup). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/421. Retained base cases 3. Retained extended cases 112.

## Mbpp/424

Write a function to extract only the rear index element of each string in the given tuple.

Arguments are provided in this order (test_tuple). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/424. Retained base cases 3. Retained extended cases 120.

## Mbpp/425

Write a function to count the number of sublists containing a particular element.

Arguments are provided in this order (list1, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/425. Retained base cases 3. Retained extended cases 108.

## Mbpp/426

Write a function to filter odd numbers.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/426. Retained base cases 3. Retained extended cases 103.

## Mbpp/427

Write a function to convert a date of yyyy-mm-dd format to dd-mm-yyyy format.

Arguments are provided in this order (dt). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/427. Retained base cases 3. Retained extended cases 112.

## Mbpp/428

Write a function to sort the given array by using shell sort.

Arguments are provided in this order (my_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/428. Retained base cases 3. Retained extended cases 107.

## Mbpp/429

Write a function to extract the elementwise and tuples from the given two tuples.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/429. Retained base cases 3. Retained extended cases 113.

## Mbpp/430

Write a function to find the directrix of a parabola.

Arguments are provided in this order (a, b, c). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/430. Retained base cases 3. Retained extended cases 102.

## Mbpp/433

Write a function to check whether the entered number is greater than the elements of the given array.

Arguments are provided in this order (arr, number). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/433. Retained base cases 3. Retained extended cases 103.

## Mbpp/436

Write a JavaScript function to return the negative numbers in a list.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/436. Retained base cases 3. Retained extended cases 111.

## Mbpp/437

Write a function to remove odd characters in a string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/437. Retained base cases 3. Retained extended cases 103.

## Mbpp/440

Write a function to find the first adverb and their positions in a given sentence.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/440. Retained base cases 3. Retained extended cases 103.

## Mbpp/441

Write a function to find the surface area of a cube of a given size.
Cube surface covers six square faces.
The side is a finite nonnegative numeric value. Boolean inputs are excluded.

Arguments are provided in this order (l). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/441. Retained base cases 3. Retained extended cases 48.

## Mbpp/445

Write a function to perform index wise multiplication of tuple elements in the given two tuples.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/445. Retained base cases 3. Retained extended cases 107.

## Mbpp/446

Write a JavaScript function to count the occurence of all elements of list in a tuple.

Arguments are provided in this order (tup, lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/446. Retained base cases 3. Retained extended cases 104.

## Mbpp/447

Write a function to find cubes of individual elements in a list.
Cube every numeric element in list order.

Arguments are provided in this order (nums). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/447. Retained base cases 3. Retained extended cases 105.

## Mbpp/448

Write a function to calculate the sum of perrin numbers.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/448. Retained base cases 3. Retained extended cases 101.

## Mbpp/450

Write a function to extract specified size of strings from a given list of string values.

Arguments are provided in this order (str1, l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/450. Retained base cases 3. Retained extended cases 105.

## Mbpp/451

Write a function to remove all whitespaces from the given string.

Arguments are provided in this order (text1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/451. Retained base cases 3. Retained extended cases 109.

## Mbpp/453

Write a JavaScript function to find the sum of even factors of a number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/453. Retained base cases 3. Retained extended cases 105.

## Mbpp/454

Write a function that matches a word containing 'z'.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/454. Retained base cases 3. Retained extended cases 103.

## Mbpp/455

Write a function to check whether the given month number contains 31 days or not.

Arguments are provided in this order (monthnum2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/455. Retained base cases 3. Retained extended cases 13.

## Mbpp/456

Write a function to reverse each string in a given list of string values.

Arguments are provided in this order (stringlist). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/456. Retained base cases 3. Retained extended cases 106.

## Mbpp/457

Write a JavaScript function to find the sublist having minimum length.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/457. Retained base cases 3. Retained extended cases 121.

## Mbpp/458

Write a function to find the area of a rectangle.
Area from the two nonnegative rectangle dimensions.

Arguments are provided in this order (l, b). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/458. Retained base cases 3. Retained extended cases 103.

## Mbpp/459

Write a function to remove uppercase substrings from a given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/459. Retained base cases 3. Retained extended cases 103.

## Mbpp/460

Write a JavaScript function to get the first element of each sublist.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/460. Retained base cases 3. Retained extended cases 120.

## Mbpp/462

Write a function to find all possible combinations of the elements of a given list.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/462. Retained base cases 3. Retained extended cases 104.

## Mbpp/463

Write a function to find the maximum product subarray of the given array.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/463. Retained base cases 3. Retained extended cases 105.

## Mbpp/465

Write a function to drop empty items from a given dictionary.

Arguments are provided in this order (dict1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/465. Retained base cases 3. Retained extended cases 110.

## Mbpp/468

Write a function to find the maximum product formed by multiplying numbers of an increasing subsequence of that array.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/468. Retained base cases 3. Retained extended cases 110.

## Mbpp/470

Write a function to find the pairwise addition of the neighboring elements of the given tuple.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/470. Retained base cases 3. Retained extended cases 109.

## Mbpp/471

Write a JavaScript function to find the product of the array multiplication modulo n.

Arguments are provided in this order (arr, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/471. Retained base cases 3. Retained extended cases 101.

## Mbpp/472

Write a JavaScript function to check whether the given list contains consecutive numbers or not.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/472. Retained base cases 3. Retained extended cases 101.

## Mbpp/474

Write a function to replace characters in a string.

Arguments are provided in this order (str1, ch, newch). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/474. Retained base cases 3. Retained extended cases 104.

## Mbpp/475

Write a function to sort a dictionary by value.

Arguments are provided in this order (dict1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/475. Retained base cases 3. Retained extended cases 111.

## Mbpp/476

Write a JavaScript function to find the sum of the largest and smallest value in a given array.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/476. Retained base cases 3. Retained extended cases 101.

## Mbpp/477

Write a JavaScript function to convert the given string to lower case.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/477. Retained base cases 3. Retained extended cases 110.

## Mbpp/478

Write a function to remove lowercase substrings from a given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/478. Retained base cases 3. Retained extended cases 104.

## Mbpp/554

Write a JavaScript function which takes a list of integers and only returns the odd ones.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/554. Retained base cases 3. Retained extended cases 104.

## Mbpp/555

Write a JavaScript function to find the difference between the sum of cubes of the first n natural numbers and the sum of the first n natural numbers.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/555. Retained base cases 3. Retained extended cases 103.

## Mbpp/556

Write a JavaScript function to count the number of pairs whose xor value is odd.

Arguments are provided in this order (A, N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/556. Retained base cases 3. Retained extended cases 103.

## Mbpp/557

Write a function to toggle the case of all characters in a string.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/557. Retained base cases 3. Retained extended cases 102.

## Mbpp/559

Write a function to find the sum of the largest contiguous sublist in the given list.

Arguments are provided in this order (a, size). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/559. Retained base cases 3. Retained extended cases 109.

## Mbpp/560

Write a function to find the union of the elements of two given tuples and output them in sorted order.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/560. Retained base cases 3. Retained extended cases 129.

## Mbpp/562

Write a JavaScript function to find the length of the longest sublists.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/562. Retained base cases 3. Retained extended cases 106.

## Mbpp/563

Write a function to extract values between quotation marks from a string.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/563. Retained base cases 3. Retained extended cases 106.

## Mbpp/564

Write a JavaScript function which takes a list of integers and counts the number of possible unordered pairs where both elements are unequal.

Arguments are provided in this order (arr, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/564. Retained base cases 3. Retained extended cases 109.

## Mbpp/565

Write a JavaScript function to split a string into characters.

Arguments are provided in this order (word). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/565. Retained base cases 3. Retained extended cases 109.

## Mbpp/567

Write a function to check whether a specified list is sorted or not.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/567. Retained base cases 3. Retained extended cases 105.

## Mbpp/568

Write a function to create a list of N empty dictionaries.

Arguments are provided in this order (length). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/568. Retained base cases 3. Retained extended cases 101.

## Mbpp/569

Write a function to sort each sublist of strings in a given list of lists.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/569. Retained base cases 3. Retained extended cases 104.

## Mbpp/572

Write a JavaScript function to remove duplicate numbers from a given number of lists.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/572. Retained base cases 3. Retained extended cases 106.

## Mbpp/573

Write a JavaScript function to calculate the product of the unique numbers in a given list.
Multiply each distinct numeric value once.

Arguments are provided in this order (list_data). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/573. Retained base cases 3. Retained extended cases 101.

## Mbpp/576

Write a JavaScript function to check whether a list is sublist of another or not.

Arguments are provided in this order (A, B). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/576. Retained base cases 3. Retained extended cases 110.

## Mbpp/577

Write a JavaScript function to find the last digit in factorial of a given number.
Last decimal digit of a nonnegative integer factorial.
The factorial argument is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/577. Retained base cases 3. Retained extended cases 15.

## Mbpp/578

Write a function to interleave 3 lists of the same length into a single flat list.

Arguments are provided in this order (list1, list2, list3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/578. Retained base cases 3. Retained extended cases 110.

## Mbpp/580

Write a function to remove uneven elements in the nested mixed tuple.

Arguments are provided in this order (test_tuple). Numeric values use finite JavaScript Number values. Tuples are records with a `$tuple` array. Lists are arrays.

Source task Mbpp/580. Retained base cases 3. Retained extended cases 104.

## Mbpp/583

Write a function which returns nth catalan number.

Arguments are provided in this order (num). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/583. Retained base cases 3. Retained extended cases 18.

## Mbpp/585

Write a function to find the n most expensive items in a given dataset.

Arguments are provided in this order (items, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/585. Retained base cases 3. Retained extended cases 103.

## Mbpp/586

Write a JavaScript function to split a list at the nth eelment and add the first part to the end.

Arguments are provided in this order (l, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/586. Retained base cases 3. Retained extended cases 104.

## Mbpp/587

Write a function to convert a list to a tuple.

Arguments are provided in this order (listx). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/587. Retained base cases 3. Retained extended cases 113.

## Mbpp/588

Write a JavaScript function to find the difference between largest and smallest value in a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/588. Retained base cases 3. Retained extended cases 101.

## Mbpp/589

Write a function to find perfect squares between two given numbers.

Arguments are provided in this order (a, b). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/589. Retained base cases 3. Retained extended cases 103.

## Mbpp/591

Write a JavaScript function to interchange the first and last elements in a list.

Arguments are provided in this order (newList). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/591. Retained base cases 3. Retained extended cases 105.

## Mbpp/592

Write a JavaScript function to find the sum of the product of consecutive binomial co-efficients.
Vandermonde identity for products of adjacent binomial coefficients.
The ordinal is a positive integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/592. Retained base cases 3. Retained extended cases 102.

## Mbpp/593

Write a function to remove leading zeroes from an ip address.

Arguments are provided in this order (ip). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/593. Retained base cases 3. Retained extended cases 101.

## Mbpp/594

Write a function to find the difference of the first even and first odd number of a given list.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/594. Retained base cases 3. Retained extended cases 106.

## Mbpp/597

Write a function to find kth element from the given two sorted arrays.
Use one-based rank.
One-based rank in the union by concatenation of two sorted arrays.
Both finite numeric arrays are sorted in nondecreasing order. The rank is an integer value from one through their combined length. Boolean inputs are excluded.

Arguments are provided in this order (arr1, arr2, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/597. Retained base cases 3. Retained extended cases 16.

## Mbpp/600

Write a JavaScript function to check whether the given number is even or not.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/600. Retained base cases 3. Retained extended cases 104.

## Mbpp/603

Write a function to get all lucid numbers smaller than or equal to a given integer.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/603. Retained base cases 3. Retained extended cases 103.

## Mbpp/604

Write a function to reverse words seperated by spaces in a given string.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/604. Retained base cases 3. Retained extended cases 113.

## Mbpp/605

Write a function to check if the given integer is a prime number.

Arguments are provided in this order (num). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/605. Retained base cases 3. Retained extended cases 105.

## Mbpp/607

Write a function to search a string for a regex pattern. The function should return the matching subtring, a start index and an end index.

Arguments are provided in this order (text, pattern). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/607. Retained base cases 3. Retained extended cases 101.

## Mbpp/608

Write a JavaScript function to find nth bell number.
Bell number from the independent binomial recurrence.
The ordinal is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/608. Retained base cases 3. Retained extended cases 103.

## Mbpp/610

Write a JavaScript function which takes a list and returns a list with the same elements, but the k'th element removed.

Arguments are provided in this order (list1, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/610. Retained base cases 3. Retained extended cases 105.

## Mbpp/611

Write a function which given a matrix represented as a list of lists returns the max of the n'th column.

Arguments are provided in this order (test_list, N). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/611. Retained base cases 3. Retained extended cases 101.

## Mbpp/612

Write a JavaScript function which takes a list of lists, where each sublist has two elements, and returns a list of two lists where the first list has the first element of each sublist and the second one has the second.

Arguments are provided in this order (lst). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/612. Retained base cases 3. Retained extended cases 104.

## Mbpp/614

Write a function to find the cumulative sum of all the values that are present in the given tuple list.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/614. Retained base cases 3. Retained extended cases 110.

## Mbpp/616

Write a function which takes two tuples of the same length and performs the element wise modulo.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/616. Retained base cases 3. Retained extended cases 105.

## Mbpp/619

Write a function to move all the numbers to the end of the given string.

Arguments are provided in this order (test_str). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/619. Retained base cases 3. Retained extended cases 104.

## Mbpp/620

Write a function to find the size of the largest subset of a list of numbers so that every pair is divisible.

Arguments are provided in this order (a). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/620. Retained base cases 3. Retained extended cases 106.

## Mbpp/623

Write a function to compute the n-th power of each number in a list.
Apply the supplied exponent to every element in order.

Arguments are provided in this order (nums, n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/623. Retained base cases 3. Retained extended cases 107.

## Mbpp/624

Write a JavaScript function to convert a given string to uppercase.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/624. Retained base cases 3. Retained extended cases 109.

## Mbpp/628

Write a function to replace all spaces in the given string with '%20'.

Arguments are provided in this order (string). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/628. Retained base cases 3. Retained extended cases 117.

## Mbpp/629

Write a JavaScript function to find even numbers from a list of numbers.

Arguments are provided in this order (l). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/629. Retained base cases 3. Retained extended cases 103.

## Mbpp/630

Write a function to extract all the adjacent coordinates of the given coordinate tuple.
In each dimension take the input coordinate minus one, the coordinate, and the coordinate plus one. Return their Cartesian product in that order, including the center.
Cartesian product of each coordinate and its neighbors, including the center shown in the release example.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/630. Retained base cases 3. Retained extended cases 120.

## Mbpp/631

Write a function to replace whitespaces with an underscore and vice versa in a given string.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/631. Retained base cases 3. Retained extended cases 106.

## Mbpp/632

Write a JavaScript function to move all zeroes to the end of the given list.

Arguments are provided in this order (num_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/632. Retained base cases 3. Retained extended cases 106.

## Mbpp/633

Write a JavaScript function to find the sum of xor of all pairs of numbers in the given list.

Arguments are provided in this order (arr, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/633. Retained base cases 3. Retained extended cases 103.

## Mbpp/635

Write a function to sort the given list.

Arguments are provided in this order (iterable). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/635. Retained base cases 3. Retained extended cases 112.

## Mbpp/637

Write a function to check whether the given amount has no profit and no loss

Arguments are provided in this order (actual_cost, sale_amount). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/637. Retained base cases 3. Retained extended cases 103.

## Mbpp/638

Write a function to calculate the wind chill index rounded to the next integer given the wind velocity in km/h and a temperature in celsius.

Arguments are provided in this order (v, t). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/638. Retained base cases 3. Retained extended cases 102.

## Mbpp/639

Write a function to sum the length of the names of a given list of names after removing the names that start with a lowercase letter.

Arguments are provided in this order (sample_names). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/639. Retained base cases 3. Retained extended cases 111.

## Mbpp/641

Write a function to find the nth nonagonal number.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/641. Retained base cases 3. Retained extended cases 102.

## Mbpp/643

Write a function that checks if a strings contains 'z', except at the start and end of the word.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/643. Retained base cases 3. Retained extended cases 103.

## Mbpp/644

Write a JavaScript function to reverse an array upto a given position.

Arguments are provided in this order (input, k). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/644. Retained base cases 3. Retained extended cases 102.

## Mbpp/720

Write a function to add a dictionary to the tuple. The output should be a tuple.

Arguments are provided in this order (test_tup, test_dict). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/720. Retained base cases 3. Retained extended cases 106.

## Mbpp/722

The input is given as - a dictionary with a student name as a key and a tuple of float (student_height, student_weight) as a value, - minimal height, - minimal weight. Write a function to filter students that have height and weight above the minimum.

Arguments are provided in this order (students, h, w). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/722. Retained base cases 3. Retained extended cases 109.

## Mbpp/723

The input is defined as two lists of the same length. Write a function to count indices where the lists have the same values.

Arguments are provided in this order (nums1, nums2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/723. Retained base cases 4. Retained extended cases 109.

## Mbpp/724

Write a function that takes base and power as arguments and calculate the sum of all digits of the base to the specified power.

Arguments are provided in this order (base, power). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/724. Retained base cases 4. Retained extended cases 105.

## Mbpp/725

Write a function to extract values between quotation marks " " of the given string.

Arguments are provided in this order (text1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/725. Retained base cases 4. Retained extended cases 112.

## Mbpp/726

Write a function that takes as input a tuple of numbers (t_1,...,t_{N+1}) and returns a tuple of length N where the i-th element of the tuple is equal to t_i * t_{i+1}.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/726. Retained base cases 4. Retained extended cases 106.

## Mbpp/728

Write a function takes as input two lists [a_1,...,a_n], [b_1,...,b_n] and returns [a_1+b_1,...,a_n+b_n].

Arguments are provided in this order (lst1, lst2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/728. Retained base cases 3. Retained extended cases 109.

## Mbpp/730

Write a function to remove consecutive duplicates of a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/730. Retained base cases 4. Retained extended cases 108.

## Mbpp/732

Write a function to replace all occurrences of spaces, commas, or dots with a colon.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/732. Retained base cases 3. Retained extended cases 112.

## Mbpp/733

Write a function to find the index of the first occurrence of a given number in a sorted array.

Arguments are provided in this order (A, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/733. Retained base cases 3. Retained extended cases 102.

## Mbpp/734

Write a JavaScript function to find sum of products of all possible sublists of a given list.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/734. Retained base cases 3. Retained extended cases 104.

## Mbpp/736

Write a function to locate the left insertion point for a specified value in sorted order.

Arguments are provided in this order (a, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/736. Retained base cases 3. Retained extended cases 104.

## Mbpp/739-exact

For a positive integer n, return the smallest k such that the triangular number k(k+1)/2 has at least n digits.

Return an exact JavaScript BigInt. The argument is a BigInt.

Source task Mbpp/739. Retained base cases 3. Retained extended cases 102.

## Mbpp/741

Write a JavaScript function to check whether all the characters are same or not.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/741. Retained base cases 3. Retained extended cases 101.

## Mbpp/743

Write a function to rotate a given list by specified number of items to the right direction.

Arguments are provided in this order (l, m). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/743. Retained base cases 3. Retained extended cases 115.

## Mbpp/744

Write a function to check if the given tuple has any none value or not.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/744. Retained base cases 3. Retained extended cases 128.

## Mbpp/745

Write a function to find numbers within a given range from startnum ti endnum where every number is divisible by every digit it contains.

Arguments are provided in this order (startnum, endnum). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/745. Retained base cases 3. Retained extended cases 104.

## Mbpp/748

Write a function to put spaces between words starting with capital letters in a given string.

Arguments are provided in this order (str1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/748. Retained base cases 3. Retained extended cases 110.

## Mbpp/749

Write a function to sort a given list of strings of numbers numerically.

Arguments are provided in this order (nums_str). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/749. Retained base cases 3. Retained extended cases 104.

## Mbpp/750

Write a function to add the given tuple to the given list.

Arguments are provided in this order (test_list, test_tup). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/750. Retained base cases 3. Retained extended cases 102.

## Mbpp/751

Write a function to check if the given array represents min heap or not.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/751. Retained base cases 3. Retained extended cases 105.

## Mbpp/752

Write a function to find the nth jacobsthal number.  0, 1, 1, 3, 5, 11, 21, 43, 85, 171, 341, 683, 1365, 2731, ...
Exact Jacobsthal closed form with zero-based ordinal.
The ordinal is a nonnegative integer value. Boolean inputs are excluded.

Arguments are provided in this order (n). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/752. Retained base cases 4. Retained extended cases 101.

## Mbpp/753

Write a function to find minimum k records from tuple list.  - in this case a verbatim copy of test cases

Arguments are provided in this order (test_list, K). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/753. Retained base cases 3. Retained extended cases 103.

## Mbpp/754

We say that an element is common for lists l1, l2, l3 if it appears in all three lists under the same index. Write a function to find common elements from three lists. The function should return a list.

Arguments are provided in this order (l1, l2, l3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/754. Retained base cases 4. Retained extended cases 115.

## Mbpp/757

Write a function to count the pairs of reverse strings in the given string list.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/757. Retained base cases 3. Retained extended cases 110.

## Mbpp/759

Write a function to check whether a given string is a decimal number with a precision of 2.

Arguments are provided in this order (num). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/759. Retained base cases 5. Retained extended cases 110.

## Mbpp/760

Write a JavaScript function to check whether a list of numbers contains only one distinct element or not.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/760. Retained base cases 3. Retained extended cases 105.

## Mbpp/762

Write a function to check whether the given month number contains 30 days or not. Months are given as number from 1 to 12.

Arguments are provided in this order (monthnum3). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/762. Retained base cases 3. Retained extended cases 13.

## Mbpp/763

Write a JavaScript function to find the minimum difference between any two elements in a given array.

Arguments are provided in this order (arr, n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/763. Retained base cases 3. Retained extended cases 101.

## Mbpp/764

Write a JavaScript function to count number of digits in a given string.

Arguments are provided in this order (s). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/764. Retained base cases 4. Retained extended cases 105.

## Mbpp/765

Write a function to find nth polite number. geeksforgeeks.org/n-th-polite-number/

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/765. Retained base cases 3. Retained extended cases 108.

## Mbpp/766

Write a function to return a list of all pairs of consecutive items in a given list.

Arguments are provided in this order (l1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/766. Retained base cases 4. Retained extended cases 111.

## Mbpp/767

Write a JavaScript function to count the number of pairs whose sum is equal to ‘sum’. The funtion gets as input a list of numbers and the sum,
Count unordered pairs of distinct positions, including different pairs with the same values.
Count unordered pairs of distinct indices whose values sum to the target.
The list and target contain finite numeric values. Boolean values are excluded.

Arguments are provided in this order (arr, sum_). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/767. Retained base cases 4. Retained extended cases 96.

## Mbpp/770

Write a JavaScript function to find the sum of fourth power of first n odd natural numbers.

Arguments are provided in this order (n). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/770. Retained base cases 3. Retained extended cases 101.

## Mbpp/771

Write a function to check if the given expression is balanced or not.

Arguments are provided in this order (exp). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/771. Retained base cases 3. Retained extended cases 103.

## Mbpp/772

Write a function to remove all the words with k length in the given string.

Arguments are provided in this order (test_str, K). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/772. Retained base cases 3. Retained extended cases 106.

## Mbpp/775

Write a JavaScript function to check whether every odd index contains odd numbers of a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/775. Retained base cases 3. Retained extended cases 102.

## Mbpp/777

Write a JavaScript function to find the sum of non-repeated elements in a given list.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/777. Retained base cases 3. Retained extended cases 110.

## Mbpp/778

Write a function to pack consecutive duplicates of a given list elements into sublists.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/778. Retained base cases 3. Retained extended cases 107.

## Mbpp/780

Write a function to find the combinations of sums with tuples in the given tuple list.

Arguments are provided in this order (test_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/780. Retained base cases 4. Retained extended cases 119.

## Mbpp/782

Write a JavaScript function to find the sum of all odd length subarrays.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/782. Retained base cases 3. Retained extended cases 105.

## Mbpp/784

Write a function to find the product of first even and odd number of a given list.

Arguments are provided in this order (list1). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/784. Retained base cases 3. Retained extended cases 102.

## Mbpp/785

Write a function to convert tuple string to integer tuple.
Parse a literal tuple of integers and keep the element order.
The input string is a literal tuple of integers. Boolean tuple members are excluded.

Arguments are provided in this order (test_str). Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number. Lists and tuples are arrays.

Source task Mbpp/785. Retained base cases 4. Retained extended cases 96.

## Mbpp/786

Write a function to locate the right insertion point for a specified value in sorted order.

Arguments are provided in this order (a, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/786. Retained base cases 3. Retained extended cases 103.

## Mbpp/788

Write a function to create a new tuple from the given string and list.

Arguments are provided in this order (test_list, test_str). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/788. Retained base cases 3. Retained extended cases 101.

## Mbpp/790

Write a JavaScript function to check whether every even index contains even numbers of a given list.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/790. Retained base cases 3. Retained extended cases 111.

## Mbpp/791

Write a function to remove tuples from the given tuple.

Arguments are provided in this order (test_tup). Numeric values use finite JavaScript Number values. Tuples are records with a `$tuple` array. Lists are arrays. Dictionaries are records with a `$entries` array of ordered key/value pairs.

Source task Mbpp/791. Retained base cases 4. Retained extended cases 108.

## Mbpp/792

Write a JavaScript function to count the number of lists in a given number of lists.

Arguments are provided in this order (input_list). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/792. Retained base cases 3. Retained extended cases 115.

## Mbpp/793

Write a JavaScript function to find the last position of an element in a sorted array.

Arguments are provided in this order (arr, x). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/793. Retained base cases 3. Retained extended cases 0.

## Mbpp/796

Write function to find the sum of all items in the given dictionary.
Sum the numeric values in the dictionary.

Arguments are provided in this order (d). Numeric values use finite JavaScript Number values. Lists and tuples are arrays. Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.

Source task Mbpp/796. Retained base cases 3. Retained extended cases 103.

## Mbpp/797

Write a JavaScript function to find the sum of all odd natural numbers within the range l and r.

Arguments are provided in this order (l, r). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/797. Retained base cases 3. Retained extended cases 102.

## Mbpp/798

Write a JavaScript function to find the sum of an array.

Arguments are provided in this order (arr). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/798. Retained base cases 3. Retained extended cases 101.

## Mbpp/799

Write a function to that rotate left bits by d bits a given number. We assume that the number is 32 bit.

Arguments are provided in this order (n, d). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/799. Retained base cases 7. Retained extended cases 101.

## Mbpp/800

Write a function to remove all whitespaces from a string.

Arguments are provided in this order (text). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/800. Retained base cases 4. Retained extended cases 120.

## Mbpp/801

Write a JavaScript function to count the number of equal numbers from three given integers.

Arguments are provided in this order (x, y, z). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/801. Retained base cases 3. Retained extended cases 110.

## Mbpp/805

Write a function that returns the list in a list of lists whose sum of elements is the highest.

Arguments are provided in this order (lists). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/805. Retained base cases 3. Retained extended cases 125.

## Mbpp/806

Write a function to find maximum run of uppercase characters in the given string.

Arguments are provided in this order (test_str). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/806. Retained base cases 3. Retained extended cases 102.

## Mbpp/807

Write a JavaScript function to find the first odd number in a given list of numbers.

Arguments are provided in this order (nums). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/807. Retained base cases 3. Retained extended cases 105.

## Mbpp/808

Write a function to check if the given tuples contain the k or not.

Arguments are provided in this order (test_tup, K). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/808. Retained base cases 3. Retained extended cases 121.

## Mbpp/809

Write a function to check if each element of second tuple is smaller than its corresponding element in the first tuple.

Arguments are provided in this order (test_tup1, test_tup2). Numeric values use finite JavaScript Number values. Lists and tuples are arrays.

Source task Mbpp/809. Retained base cases 3. Retained extended cases 122.
