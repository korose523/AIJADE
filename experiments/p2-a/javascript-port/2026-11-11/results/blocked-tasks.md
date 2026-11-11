# Disposition of the 52 previously blocked tasks

The Jint column refers to the full released-case replay. The statement column gives the AI-assisted interpretation and its case counts. The accompanying JSONL gives original case identifiers, examples, representations, hashes and the proposed retained cases.

| Task | Previous condition | Treatment | Jint agreement / planned | Statement check | Disposition |
|---|---|---|---:|---|---|
| `HumanEval/8` | Integer outside safe Number range | BigInt | 1,005 / 1,005 | Sum and product of integer values, including empty identities. 1002 agrees, 3 outside domain. | Released port for author review |
| `HumanEval/15` | Incomplete reference | Complete compressed recovery | 137 / 137 | Decimal sequence 0 through n with one space between terms. 137 agrees. | Released port for author review |
| `HumanEval/35` | Float comparison | Case-specific float tolerance | 940 / 940 | Greatest member of a nonempty numeric sequence. 940 agrees. | Released port for author review |
| `HumanEval/39` | Integer outside safe Number range | BigInt | 12 / 12 | Positive Fibonacci-prime rank, checked by fast doubling and independent small-prime witnesses. 12 agrees. | Released port for author review |
| `HumanEval/41` | Integer outside safe Number range | BigInt | 83 / 83 | Every car in one group meets each car in the other group once. 83 agrees. | Released port for author review |
| `HumanEval/46` | Integer outside safe Number range | BigInt | 136 / 136 | Four-term recurrence with initial values 0, 0, 2, 0. 136 agrees. | Released port for author review |
| `HumanEval/55` | Integer outside safe Number range | BigInt | 50 / 50 | Fibonacci value with F(0)=0 and F(1)=1, checked by fast doubling. 48 agrees, 2 outside domain. | Released port for author review |
| `HumanEval/63` | Integer outside safe Number range | BigInt | 70 / 70 | Three-term recurrence with initial values 0, 0, 1. 68 agrees, 2 outside domain. | Released port for author review |
| `HumanEval/83` | Integer outside safe Number range | Exact decimal text | 109 / 109 | Inclusion-exclusion for n-digit integers starting or ending in 1. 109 agrees. | Released port for author review |
| `HumanEval/99` | Integer outside safe Number range | BigInt, 715 exact variant cases | 715 / 715 | Nearest integer to exact decimal text, with half ties away from zero. 700 agrees, 15 statement conflict. | Exact variant for author review |
| `HumanEval/106` | Integer outside safe Number range | BigInt | 108 / 108 | One-based positions alternate triangular sums and factorials. 108 agrees. | Released port for author review |
| `HumanEval/139` | Integer outside safe Number range | BigInt | 131 / 131 | Product of factorials from 1 through positive n. 131 agrees. | Released port for author review |
| `HumanEval/142` | Integer outside safe Number range | BigInt | 1,008 / 1,008 | Zero-based index test gives the square rule precedence over cubing. 1008 agrees. | Released port for author review |
| `HumanEval/160` | Integer outside safe Number range | BigInt | 452 / 452 | Allowed arithmetic and precedence on the stated nonnegative integer operands. 452 agrees. | Released port for author review |
| `Mbpp/14` | Float comparison | Case-specific float tolerance | 111 / 111 | Triangular prism volume from nonnegative length, base and height. 111 agrees. | Released port for author review |
| `Mbpp/17` | Float comparison | Case-specific float tolerance | 104 / 104 | Square perimeter equals four times its nonnegative side. 103 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/62` | Float comparison | Case-specific float tolerance | 104 / 104 | Minimum member of the nonempty numeric list. 104 agrees. | Released port for author review |
| `Mbpp/65` | Float comparison | BigInt, Case-specific float tolerance | 115 / 115 | Sum after recursively flattening numeric lists. 115 agrees. | Released port for author review |
| `Mbpp/80` | Float comparison | Case-specific float tolerance | 104 / 104 | Nonnegative ordinal tetrahedral number from a binomial coefficient. 102 agrees, 2 outside domain. | Released port for author review |
| `Mbpp/93` | Integer outside safe Number range, Float comparison | BigInt, Case-specific float tolerance | 113 / 113 | Real scalar exponentiation over the released finite inputs. 113 agrees. | Released port for author review |
| `Mbpp/126` | Float comparison | Case-specific float tolerance | 110 / 110 | Exact sum of the divisors of the greatest common divisor. 110 agrees. | Released port for author review |
| `Mbpp/133` | Float comparison | Case-specific float tolerance | 111 / 111 | Sum of strictly negative elements. 111 agrees. | Released port for author review |
| `Mbpp/145` | Float comparison | Case-specific float tolerance | 109 / 109 | Maximum absolute difference equals max minus min. 108 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/171` | Float comparison | Case-specific float tolerance | 108 / 108 | Regular pentagon perimeter equals five times the nonnegative side. 78 agrees, 30 outside domain. | Released port for author review |
| `Mbpp/227` | Float comparison | Case-specific float tolerance | 108 / 108 | Minimum of the three supplied numeric values. 108 agrees. | Released port for author review |
| `Mbpp/234` | Float comparison | Case-specific float tolerance | 104 / 104 | Cube volume from a nonnegative side. 103 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/255` | Incomplete reference | Both recovery attempts hit the RSS stop | 3 / 112 | Combinations with repetition of input positions, in input order. 3 agrees, 109 missing reference. | Hold for reference coverage |
| `Mbpp/260` | Integer outside safe Number range | BigInt | 107 / 107 | Check the published prime requirement against released sequence values. 3 outside domain, 55 statement conflict, 49 unresolved. | Hold for statement decision |
| `Mbpp/264` | Float comparison | Case-specific float tolerance | 106 / 106 | Proposed explicit convention uses 10.5 per year for the first two years and 4 thereafter. 104 agrees, 2 outside domain. | Released port for author review |
| `Mbpp/266` | Float comparison | Case-specific float tolerance | 107 / 107 | Lateral surface covers four square faces of a cube. 106 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/267` | Float comparison | Case-specific float tolerance, 121 exact variant cases | 122 / 122 | Exact sum of squares of the first n positive odd integers. 85 agrees, 1 outside domain, 36 statement conflict. | Exact variant for author review |
| `Mbpp/268` | Integer outside safe Number range | BigInt | 106 / 106 | Centered hexagram number at positive ordinal n. 105 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/271` | Integer outside safe Number range | BigInt | 110 / 110 | Exact sum of fifth powers of the first n positive even integers. 109 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/274` | Integer outside safe Number range | BigInt | 106 / 106 | Even-index binomial sum for the specified positive exponent. 105 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/287` | Float comparison | Case-specific float tolerance, 107 exact variant cases | 109 / 109 | Exact sum of squares of the first n positive even integers. 90 agrees, 2 outside domain, 17 statement conflict. | Exact variant for author review |
| `Mbpp/391` | Typed dictionary keys | Ordered typed entries | 107 / 107 | Three lists form a list of nested mappings. The proposed contract specifies truncation to the shortest list. 107 agrees. | Released port for author review |
| `Mbpp/409` | Integer outside safe Number range | BigInt | 114 / 114 | Minimum product across the given pairs. 114 agrees. | Released port for author review |
| `Mbpp/441` | Integer outside safe Number range, Float comparison | BigInt, Case-specific float tolerance | 124 / 124 | Cube surface covers six square faces. 51 agrees, 73 outside domain. | Released port for author review |
| `Mbpp/447` | Integer outside safe Number range | BigInt | 108 / 108 | Cube every numeric element in list order. 108 agrees. | Released port for author review |
| `Mbpp/458` | Integer outside safe Number range, Float comparison | BigInt, Case-specific float tolerance | 106 / 106 | Area from the two nonnegative rectangle dimensions. 106 agrees. | Released port for author review |
| `Mbpp/573` | Integer outside safe Number range | BigInt | 104 / 104 | Multiply each distinct numeric value once. 104 agrees. | Released port for author review |
| `Mbpp/577` | Float comparison | Case-specific float tolerance | 108 / 108 | Last decimal digit of a nonnegative integer factorial. 18 agrees, 90 outside domain. | Released port for author review |
| `Mbpp/592` | Integer outside safe Number range | BigInt | 106 / 106 | Vandermonde identity for products of adjacent binomial coefficients. 105 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/597` | Float comparison | Case-specific float tolerance | 107 / 107 | One-based rank in the union by concatenation of two sorted arrays. 19 agrees, 88 outside domain. | Released port for author review |
| `Mbpp/608` | Integer outside safe Number range | BigInt | 108 / 108 | Bell number from the independent binomial recurrence. 106 agrees, 2 outside domain. | Released port for author review |
| `Mbpp/623` | Integer outside safe Number range | BigInt | 110 / 110 | Apply the supplied exponent to every element in order. 110 agrees. | Released port for author review |
| `Mbpp/630` | Incomplete reference | Complete compressed recovery | 123 / 123 | Cartesian product of each coordinate and its neighbors, including the center shown in the release example. 123 agrees. | Released port for author review |
| `Mbpp/739` | Integer outside safe Number range | BigInt, 105 exact variant cases | 105 / 106 | Smallest triangular index reaching the exact n-digit threshold. 35 agrees, 1 outside domain, 70 statement conflict. | Exact variant for author review |
| `Mbpp/752` | Integer outside safe Number range | BigInt | 106 / 106 | Exact Jacobsthal closed form with zero-based ordinal. 105 agrees, 1 outside domain. | Released port for author review |
| `Mbpp/767` | Float comparison | Case-specific float tolerance | 107 / 107 | Count unordered pairs of distinct indices whose values sum to the target. 100 agrees, 7 outside domain. | Released port for author review |
| `Mbpp/785` | Integer outside safe Number range | BigInt | 121 / 121 | Parse a literal tuple of integers and keep the element order. 100 agrees, 21 outside domain. | Released port for author review |
| `Mbpp/796` | Float comparison | Case-specific float tolerance | 106 / 106 | Sum the numeric values in the dictionary. 106 agrees. | Released port for author review |
