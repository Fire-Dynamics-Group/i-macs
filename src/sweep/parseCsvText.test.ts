import { describe, expect, it } from "vitest";
import { parseCsvText } from "./parseCsvText";

describe("parseCsvText", () => {
  it("parses a comma-separated list of integers", () => {
    expect(parseCsvText("1, 2, 3")).toEqual([1, 2, 3]);
  });

  it("parses decimals", () => {
    expect(parseCsvText("1.5, 2.5, 3.75")).toEqual([1.5, 2.5, 3.75]);
  });

  it("accepts newline as a delimiter alongside commas", () => {
    expect(parseCsvText("1, 2\n3, 4\r\n5")).toEqual([1, 2, 3, 4, 5]);
  });

  it("strips whitespace around tokens", () => {
    expect(parseCsvText("  1  ,  2 \t,\n3 ")).toEqual([1, 2, 3]);
  });

  it("drops empty tokens between delimiters", () => {
    expect(parseCsvText("1,,2,,,3")).toEqual([1, 2, 3]);
  });

  it("returns an empty array for empty input", () => {
    expect(parseCsvText("")).toEqual([]);
    expect(parseCsvText("   ")).toEqual([]);
    expect(parseCsvText(",,\n,,")).toEqual([]);
  });

  it("supports negative numbers and scientific notation", () => {
    expect(parseCsvText("-1, -2.5, 1e3, 2.5e-2")).toEqual([-1, -2.5, 1000, 0.025]);
  });

  it("throws with the bad token in the error message on a non-numeric value", () => {
    expect(() => parseCsvText("1, 2, abc, 4")).toThrowError(/abc/);
  });

  it("rejects NaN-producing tokens with the bad token in the error", () => {
    expect(() => parseCsvText("1, NaN, 2")).toThrowError(/NaN/);
  });

  it("rejects infinity tokens", () => {
    expect(() => parseCsvText("1, Infinity, 2")).toThrowError(/Infinity/);
  });
});
