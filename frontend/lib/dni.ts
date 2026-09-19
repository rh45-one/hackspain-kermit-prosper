const DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE";

export function dniControlLetter(digits: number): string {
  return DNI_LETTERS[digits % 23] ?? "";
}

export type IdParseResult =
  | { status: "empty" }
  | { status: "partial"; normalized: string }
  | { status: "valid"; normalized: string }
  | { status: "invalid"; error: string };

function compactId(raw: string): string {
  return raw.trim().toUpperCase().replace(/[\s.-]/g, "");
}

export function parseSpanishId(raw: string): IdParseResult {
  const value = compactId(raw);
  if (!value) {
    return { status: "empty" };
  }

  const nie = value.match(/^([XYZ])(\d{0,7})([A-Z]?)$/);
  if (nie) {
    const [, letter, digits, control] = nie;
    if (digits.length < 7 || control.length === 0) {
      return { status: "partial", normalized: value };
    }
    const prefix = { X: "0", Y: "1", Z: "2" }[letter] ?? "0";
    const expected = dniControlLetter(Number(`${prefix}${digits}`));
    if (control !== expected) {
      return {
        status: "invalid",
        error: `Invalid control letter (expected ${expected})`,
      };
    }
    return { status: "valid", normalized: value };
  }

  const dni = value.match(/^(\d{1,8})([A-Z]?)$/);
  if (dni) {
    const [, digits, control] = dni;
    if (digits.length < 8 || control.length === 0) {
      return { status: "partial", normalized: value };
    }
    const expected = dniControlLetter(Number(digits));
    if (control !== expected) {
      return {
        status: "invalid",
        error: `Invalid control letter (expected ${expected})`,
      };
    }
    return { status: "valid", normalized: value };
  }

  return { status: "invalid", error: "Unrecognised DNI/NIE format" };
}

export function isValidTunnelUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("wss://") || trimmed.startsWith("ws://");
}
