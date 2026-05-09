import SwiftUI

struct PortfolioChartView: View {
    let points: [Double]
    /// Raw equity values parallel to `points`, used by the scrub label so
    /// it reflects the actual price at the dragged index. If empty or
    /// length-mismatched, the scrub label falls back to no value.
    var values: [Decimal] = []
    /// Bar timestamps parallel to `points`, formatted into the secondary
    /// scrub label (e.g. "9:31 AM" for 1D, "Mar 5" for 1M+). Same length
    /// rule as `values`.
    var dates: [Date] = []
    var currency: String = "USD"
    var range: TimeRange = .oneMonth
    let scale: CGFloat
    @Binding var scrubValue: String?

    @State private var scrubIndex: Int?
    @State private var scrubDate: String?
    @State private var displayPoints: [Double] = []
    @State private var fadeOpacity: Double = 1
    @State private var pendingRangeSwap = false

    private static let chartLabelTimeZone = TimeZone(identifier: "America/New_York") ?? .current

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let height = geo.size.height

            ZStack(alignment: .bottom) {
                ChartFill(points: displayPoints, size: geo.size)
                    .fill(
                        LinearGradient(
                            colors: [Color.sevinoPositive.opacity(0.3), Color.sevinoPositive.opacity(0.02)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                ChartLine(points: displayPoints, size: geo.size)
                    .stroke(Color.sevinoPositive, lineWidth: 2 * scale)

                if let idx = scrubIndex, idx < displayPoints.count, let label = scrubValue {
                    let step = width / CGFloat(displayPoints.count - 1)
                    let x = CGFloat(idx) * step
                    let y = height - (CGFloat(displayPoints[idx]) * height)
                    let labelOffset: CGFloat = scrubDate == nil ? 40 : 50
                    let labelX = min(max(x, labelOffset * scale), width - labelOffset * scale)

                    Rectangle()
                        .fill(Color.sevinoGreyContrast.opacity(0.5))
                        .frame(width: 1 * scale)
                        .position(x: x, y: height / 2)
                        .accessibilityHidden(true)

                    Circle()
                        .fill(Color.sevinoPositive)
                        .frame(width: 8 * scale, height: 8 * scale)
                        .position(x: x, y: y)
                        .accessibilityHidden(true)

                    VStack(spacing: 1 * scale) {
                        Text(label)
                            .font(.system(size: 12 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                        if let date = scrubDate {
                            Text(date)
                                .font(.system(size: 10 * scale, weight: .regular))
                                .foregroundStyle(Color.sevinoGreyContrast)
                        }
                    }
                    .padding(.horizontal, 8 * scale)
                    .padding(.vertical, 4 * scale)
                    .modifier(SevinoGlass.nav)
                    .position(x: labelX, y: y - (scrubDate == nil ? 20 : 28) * scale)
                    .accessibilityHidden(true)
                }
            }
            .contentShape(.rect)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        updateScrub(at: value.location.x, width: width)
                    }
                    .onEnded { _ in
                        scrubIndex = nil
                        scrubValue = nil
                        scrubDate = nil
                    }
            )
        }
        .opacity(fadeOpacity)
        .onChange(of: points) { _, newValue in
            if pendingRangeSwap {
                // New data arrived during the fade-out budget — fade in
                // early. The `.task(id: range)` fallback will see
                // `pendingRangeSwap == false` and skip its fade-in.
                displayPoints = newValue
                pendingRangeSwap = false
                withAnimation(.easeIn(duration: 0.25)) {
                    fadeOpacity = 1
                }
            } else {
                // Same-range refresh — snap. Animating tick-level
                // differences reads as the chart "wobbling" without a
                // gesture motivating it.
                displayPoints = newValue
            }
        }
        .task(id: range) {
            // Fires on first appearance and on every range change.
            // Auto-cancels on view disappear or on the next range change.
            if displayPoints.isEmpty {
                displayPoints = points
                return
            }

            // Range switch: fade out, wait for the new data (or a fixed
            // budget — on a young account several long ranges return the
            // same daily bars, so `.onChange(of: points)` won't fire and
            // the fade-in needs to trigger anyway), then fade back in.
            //
            // 200ms matches measured Alpaca round-trip via the local
            // backend (~70–230ms parallel snapshot+history) and lands
            // right after the 180ms fade-out completes.
            pendingRangeSwap = true
            withAnimation(.easeOut(duration: 0.18)) {
                fadeOpacity = 0
            }

            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled, pendingRangeSwap else { return }
            displayPoints = points
            pendingRangeSwap = false
            withAnimation(.easeIn(duration: 0.25)) {
                fadeOpacity = 1
            }
        }
    }

    private func updateScrub(at x: CGFloat, width: CGFloat) {
        guard displayPoints.count > 1 else { return }
        let step = width / CGFloat(displayPoints.count - 1)
        let idx = min(max(Int((x / step).rounded()), 0), displayPoints.count - 1)
        scrubIndex = idx
        scrubValue = Self.scrubLabel(
            at: idx,
            values: values,
            expectedCount: points.count,
            currency: currency
        )
        scrubDate = Self.scrubDateLabel(
            at: idx,
            dates: dates,
            expectedCount: points.count,
            range: range
        )
    }

    /// Returns the formatted equity at the dragged index, or `nil` when
    /// `values` is missing or length-mismatched against `points` (only
    /// possible if a caller passes a non-parallel `values` array — the
    /// production wiring in `PortfolioService` always emits parallel
    /// arrays). Pure helper so the fallback branch is unit-testable.
    static func scrubLabel(
        at idx: Int,
        values: [Decimal],
        expectedCount: Int,
        currency: String
    ) -> String? {
        guard values.count == expectedCount, idx >= 0, idx < values.count else {
            return nil
        }
        return values[idx].asCurrency(currencyCode: currency)
    }

    /// Returns the formatted timestamp at the dragged index, with a format
    /// that scales with the visible range — Apple Stocks pattern:
    /// - 1D     → "9:31 AM"
    /// - 1W     → "Mon 10:00 AM"
    /// - 1M..YTD→ "Mar 5"
    /// - 1Y     → "Mar 5, '25"
    /// - ALL    → "Mar 2023"
    /// Times are rendered in `America/New_York` so 1D/1W show market-clock
    /// regardless of the user's device locale. Returns `nil` if `dates` is
    /// missing or length-mismatched against the parallel arrays.
    static func scrubDateLabel(
        at idx: Int,
        dates: [Date],
        expectedCount: Int,
        range: TimeRange
    ) -> String? {
        guard dates.count == expectedCount, idx >= 0, idx < dates.count else {
            return nil
        }
        let date = dates[idx]
        let tz = Self.chartLabelTimeZone
        switch range {
        case .oneDay:
            return date.formatted(
                Date.FormatStyle(timeZone: tz).hour().minute()
            )
        case .oneWeek:
            return date.formatted(
                Date.FormatStyle(timeZone: tz)
                    .weekday(.abbreviated)
                    .hour()
                    .minute()
            )
        case .oneMonth, .threeMonths, .sixMonths, .ytd:
            return date.formatted(
                Date.FormatStyle(timeZone: tz)
                    .month(.abbreviated)
                    .day()
            )
        case .oneYear:
            return date.formatted(
                Date.FormatStyle(timeZone: tz)
                    .month(.abbreviated)
                    .day()
                    .year(.twoDigits)
            )
        case .all:
            return date.formatted(
                Date.FormatStyle(timeZone: tz)
                    .month(.abbreviated)
                    .year()
            )
        }
    }
}

private struct ChartLine: Shape {
    let points: [Double]
    let size: CGSize

    func path(in rect: CGRect) -> Path {
        guard points.count > 1 else { return Path() }
        let step = size.width / CGFloat(points.count - 1)

        return Path { path in
            for (index, point) in points.enumerated() {
                let x = CGFloat(index) * step
                let y = size.height - (CGFloat(point) * size.height)
                if index == 0 {
                    path.move(to: CGPoint(x: x, y: y))
                } else {
                    path.addLine(to: CGPoint(x: x, y: y))
                }
            }
        }
    }
}

private struct ChartFill: Shape {
    let points: [Double]
    let size: CGSize

    func path(in rect: CGRect) -> Path {
        guard points.count > 1 else { return Path() }
        let step = size.width / CGFloat(points.count - 1)

        return Path { path in
            path.move(to: CGPoint(x: 0, y: size.height))
            for (index, point) in points.enumerated() {
                let x = CGFloat(index) * step
                let y = size.height - (CGFloat(point) * size.height)
                path.addLine(to: CGPoint(x: x, y: y))
            }
            path.addLine(to: CGPoint(x: size.width, y: size.height))
            path.closeSubpath()
        }
    }
}

#Preview {
    PortfolioChartView(
        points: (0..<40).map { _ in Double.random(in: 0.1...0.9) },
        scale: 1,
        scrubValue: .constant(nil)
    )
    .frame(height: 160)
    .padding()
    .background(Color.sevinoPrimary)
}
