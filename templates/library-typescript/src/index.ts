/**
 * The public API of the package: everything exported here is what consumers import from the package name.
 * Replace this sample with the library's own code; keep each export documented and tested.
 */
export interface Greeting {
  readonly name: string;
  readonly text: string;
}

/** A greeting for `name`; a blank name is refused, so callers never publish an empty greeting. */
export function greet(name: string): Greeting {
  const trimmed = name.trim();
  if (trimmed === "") {
    throw new RangeError("name must not be blank");
  }
  return { name: trimmed, text: `Hello, ${trimmed}!` };
}
