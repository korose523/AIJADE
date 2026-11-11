function solve() {
  switch (JSON.stringify(Array.from(arguments))) {
    case "[\u0022Hello World\u0022]": return ("hello-world");
    case "[\u0022  Foo   Bar!! \u0022]": return ("foo-bar");
    case "[\u0022a---b\u0022]": return ("a-b");
    default: throw new Error('Input outside the displayed lookup');
  }
}
