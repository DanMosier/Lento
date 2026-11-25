import { describe, expect, it } from "vitest";
import { fitZoom, pageLayout, parseScoreSize, phoneScreen } from "../src/practice/layout";

describe("fitting the score to the screen", () => {
  it("draws smaller on a phone held upright, so several measures fit on a line", () => {
    expect(fitZoom(390)).toBe(0.6);
    expect(fitZoom(600)).toBeCloseTo(0.79, 2);
    expect(fitZoom(1200)).toBe(1);
  });
  it("caps the size on a phone on its side, so another line of music fits", () => {
    expect(fitZoom(850, "auto", true)).toBe(0.8);
    expect(fitZoom(390, "auto", true)).toBe(0.6);
  });
  it("uses a fixed size when one is chosen", () => {
    expect(fitZoom(390, 100)).toBe(1);
    expect(fitZoom(1200, 50, true)).toBe(0.5);
  });
  it("narrows margins and drops a lone part's name on a phone, but not on a wide screen", () => {
    expect(pageLayout(390, "auto", 1)).toEqual({ zoom: 0.6, margin: 2, partNames: false });
    expect(pageLayout(390, "auto", 2).partNames).toBe(true);
    expect(pageLayout(1200, "auto", 1)).toEqual({ zoom: 1, margin: 5, partNames: true });
  });
  it("tells phones from tablets by the screen's short side", () => {
    expect(phoneScreen({ width: 393, height: 851 })).toBe(true);
    expect(phoneScreen({ width: 851, height: 393 })).toBe(true);
    expect(phoneScreen({ width: 800, height: 1280 })).toBe(false);
  });
  it("reads saved sizes safely", () => {
    expect(parseScoreSize("70")).toBe(70);
    expect(parseScoreSize("auto")).toBe("auto");
    expect(parseScoreSize("13")).toBe("auto");
    expect(parseScoreSize(null)).toBe("auto");
  });
});
