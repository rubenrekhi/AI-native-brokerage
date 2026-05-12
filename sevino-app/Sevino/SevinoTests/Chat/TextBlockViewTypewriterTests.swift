import XCTest
@testable import Sevino

/**
 Pins down the typewriter math that drives streaming text blocks (SEV-570).

 The buffer is the per-tick step of the typewriter loop: given the currently
 displayed prefix and the latest `block.text` target, it returns the next prefix
 to render. These tests stand in for the loop by repeatedly invoking `advance`
 — no clock, no async — and assert the two invariants the view relies on:

 1. The displayed prefix grows monotonically while the target keeps extending.
 2. The buffer converges on the final target after a finite number of ticks.
 */
final class TextBlockViewTypewriterTests: XCTestCase {

    // MARK: - chunkSize

    func testChunkSize_smallRemainingTypesOneCharPerTick() {
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 1), 1)
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 47), 1)
    }

    func testChunkSize_catchUpAcceleratesPastTypewriterRange() {
        // Past 47 chars behind we exceed the ≥ 60 cps floor the acceptance
        // criterion calls for: 2 chars × 21 ms tick ≈ 95 cps.
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 48), 2)
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 120), 2)
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 121), 5)
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 600), 5)
    }

    func testChunkSize_bigBacklogScalesLinearly() {
        // A 3000-char delta should converge in roughly one second of typing,
        // not sixty: max(8, 3000 / 50) = 60 chars per 21 ms tick ≈ 2800 cps.
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 601), max(8, 601 / 50))
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 3000), 60)
    }

    func testChunkSize_zeroRemainingReturnsZero() {
        XCTAssertEqual(TypewriterStreamingBuffer.chunkSize(forRemaining: 0), 0)
    }

    // MARK: - advance

    func testAdvance_monotonicCatchUpOnAppendingTarget() {
        let target = String(repeating: "a", count: 250)
        var displayed = ""
        var ticks = 0
        let maxTicks = 2_000

        while displayed != target {
            let next = TypewriterStreamingBuffer.advance(from: displayed, toward: target)
            XCTAssertGreaterThan(next.count, displayed.count, "advance must always grow until convergence")
            XCTAssertTrue(target.hasPrefix(next), "next prefix must remain a prefix of target")
            displayed = next
            ticks += 1
            if ticks >= maxTicks { break }
        }

        XCTAssertEqual(displayed, target)
        XCTAssertLessThan(ticks, maxTicks, "buffer should converge well under the safety bound")
    }

    func testAdvance_targetGrowsMidStreamStaysMonotonic() {
        // Simulate the streaming case: target keeps extending in chunks while
        // the typewriter is still catching up. `displayed` must never shrink.
        let chunks = ["Hel", "Hello", "Hello world", "Hello world, how are you doing today?"]
        var displayed = ""
        var nextTargetIndex = 0
        var ticks = 0

        while displayed != chunks.last {
            // Every 3 ticks advance the streaming target to its next stage.
            if ticks % 3 == 0, nextTargetIndex < chunks.count - 1 {
                nextTargetIndex += 1
            }
            let target = chunks[nextTargetIndex]
            let next = TypewriterStreamingBuffer.advance(from: displayed, toward: target)
            XCTAssertGreaterThanOrEqual(next.count, displayed.count, "displayed must never regress")
            displayed = next
            ticks += 1
            if ticks > 1_000 { break }
        }

        XCTAssertEqual(displayed, chunks.last)
    }

    func testAdvance_divergentTargetSnaps() {
        // `block_data` patches can replace the text wholesale. When the target
        // no longer extends the displayed prefix, the buffer snaps to it so the
        // view never renders a stale prefix of an unrelated string.
        let displayed = "Hello"
        let target = "Completely different copy"

        let next = TypewriterStreamingBuffer.advance(from: displayed, toward: target)

        XCTAssertEqual(next, target)
    }

    func testAdvance_emptyTargetIsNoOp() {
        XCTAssertEqual(TypewriterStreamingBuffer.advance(from: "", toward: ""), "")
    }

    func testAdvance_targetShorterThanDisplayedSnaps() {
        // Defensive: if a future patch ever shortens the text, snap rather than
        // looping forever or rendering a phantom suffix.
        let next = TypewriterStreamingBuffer.advance(from: "Hello world", toward: "Hi")
        XCTAssertEqual(next, "Hi")
    }

    func testAdvance_largeBacklogConvergesInBoundedTicks() {
        // A 3000-char dump arriving in one delta must catch up in a bounded
        // number of ticks — not a string-length-proportional one. The bands
        // give roughly: phase >600 shrinks 3000→600 in ~80 ticks, 600→120 at
        // 5/tick is ~96 ticks, 120→47 at 2/tick is ~36 ticks, 47→0 at 1/tick
        // is 47 ticks. ≤ 300 ticks (≈ 6.3 s at the 21 ms tick) covers it.
        let target = String(repeating: "x", count: 3_000)
        var displayed = ""
        var ticks = 0

        while displayed != target {
            displayed = TypewriterStreamingBuffer.advance(from: displayed, toward: target)
            ticks += 1
            if ticks > 500 { break }
        }

        XCTAssertEqual(displayed, target)
        XCTAssertLessThanOrEqual(ticks, 300, "3000-char backlog should converge in ≤ ~300 ticks")
    }
}
