import SwiftUI
import UIKit

@MainActor
private var widthScale: CGFloat {
    min(UIScreen.main.bounds.width / 393, 1.25)
}

struct PortfolioDistributionCard: View {
    let data: PortfolioDistributionData
    @State private var selectedSegmentID: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            DistributionHeaderView(
                totalValue: data.totalValue,
                currencyCode: data.currencyCode
            )
            StackedBarView(
                segments: data.segments,
                currencyCode: data.currencyCode,
                selectedSegmentID: $selectedSegmentID
            )
                .padding(.top, 44 * widthScale)
            DistributionLegendView(
                segments: data.segments,
                currencyCode: data.currencyCode
            )
                .padding(.top, 32 * widthScale)
        }
        .padding(20 * widthScale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(SevinoGlass.card)
    }
}

private struct DistributionHeaderView: View {
    let totalValue: Decimal
    let currencyCode: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6 * widthScale) {
            Text(totalValue.formatted(.currency(code: currencyCode).precision(.fractionLength(2))))
                .font(.largeTitle.bold())
                .foregroundStyle(Color.sevinoSecondary)
            Text(L10n.Home.portfolioCurrency)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
    }
}

private struct StackedBarView: View {
    let segments: [DistributionSegment]
    let currencyCode: String
    @Binding var selectedSegmentID: String?

    private var barHeight: CGFloat { 40 * widthScale }
    private var barDepth: CGFloat { 14 * widthScale }
    private var calloutWidth: CGFloat { 140 * widthScale }
    private var calloutSpacing: CGFloat { 8 * widthScale }

    var body: some View {
        GeometryReader { proxy in
            let totalWidth = max(proxy.size.width - barDepth, 0)
            let laidOut = layout(totalWidth: totalWidth)
            let selected = laidOut.first { $0.id == selectedSegmentID }

            ZStack(alignment: .topLeading) {
                ForEach(laidOut) { item in
                    TopFaceShape(depth: barDepth)
                        .fill(item.segment.colorToken.color)
                        .brightness(0.08)
                        .opacity(opacity(for: item.segment))
                        .frame(width: item.width + barDepth, height: barDepth)
                        .offset(x: item.xStart, y: 0)
                        .accessibilityHidden(true)
                }

                if let lastSegment = segments.last {
                    RightFaceShape(depth: barDepth)
                        .fill(lastSegment.colorToken.color)
                        .brightness(-0.12)
                        .opacity(opacity(for: lastSegment))
                        .frame(width: barDepth, height: barHeight + barDepth)
                        .offset(x: totalWidth, y: 0)
                        .accessibilityHidden(true)
                }

                HStack(spacing: 0) {
                    ForEach(segments) { segment in
                        Button {
                            selectedSegmentID = selectedSegmentID == segment.id ? nil : segment.id
                        } label: {
                            Rectangle()
                                .fill(segment.colorToken.color)
                                .opacity(opacity(for: segment))
                                .frame(
                                    width: totalWidth * CGFloat(segment.fraction),
                                    height: barHeight
                                )
                                .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(Text(segment.label))
                        .accessibilityValue(Text(
                            L10n.Home.portfolioDistributionSegmentAccessibility(
                                segment.label,
                                segment.fraction.formatted(.percent.precision(.fractionLength(1))),
                                segment.amount.formatted(.currency(code: currencyCode).precision(.fractionLength(2)))
                            )
                        ))
                        .accessibilityAddTraits(
                            segment.id == selectedSegmentID ? [.isButton, .isSelected] : .isButton
                        )
                    }
                }
                .offset(x: 0, y: barDepth)

                if let selected {
                    let rawX = selected.xStart + selected.width / 2 - calloutWidth / 2
                    let clampedX = min(max(rawX, 0), max(totalWidth + barDepth - calloutWidth, 0))
                    SegmentCallout(segment: selected.segment, currencyCode: currencyCode)
                        .frame(width: calloutWidth)
                        .offset(x: clampedX, y: -(calloutSpacing + barHeight))
                        .transition(.opacity.combined(with: .scale(scale: 0.85, anchor: .bottom)))
                        .accessibilityHidden(true)
                }
            }
            .animation(.easeInOut(duration: 0.2), value: selectedSegmentID)
        }
        .frame(height: barHeight + barDepth)
    }

    private func opacity(for segment: DistributionSegment) -> Double {
        guard let selectedSegmentID else { return 1.0 }
        return segment.id == selectedSegmentID ? 1.0 : 0.25
    }

    private func layout(totalWidth: CGFloat) -> [SegmentLayout] {
        var x: CGFloat = 0
        return segments.map { segment in
            let width = totalWidth * CGFloat(segment.fraction)
            let layout = SegmentLayout(segment: segment, xStart: x, width: width)
            x += width
            return layout
        }
    }
}

private struct SegmentCallout: View {
    let segment: DistributionSegment
    let currencyCode: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2 * widthScale) {
            HStack(spacing: 6 * widthScale) {
                Circle()
                    .fill(segment.colorToken.color)
                    .frame(width: 8 * widthScale, height: 8 * widthScale)
                Text(segment.label)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                Spacer(minLength: 4 * widthScale)
                Text(segment.fraction.formatted(.percent.precision(.fractionLength(1))))
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            Text(segment.amount.formatted(.currency(code: currencyCode).precision(.fractionLength(2))))
                .font(.caption2)
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .padding(.horizontal, 10 * widthScale)
        .padding(.vertical, 6 * widthScale)
        .background(
            RoundedRectangle(cornerRadius: 10 * widthScale)
                .fill(Color.sevinoSettingsContrast)
                .shadow(color: .black.opacity(0.15), radius: 8 * widthScale, y: 2 * widthScale)
        )
    }
}

private struct DistributionLegendView: View {
    let segments: [DistributionSegment]
    let currencyCode: String

    var body: some View {
        VStack(spacing: 18 * widthScale) {
            ForEach(segments) { segment in
                LegendRow(segment: segment, currencyCode: currencyCode)
            }
        }
    }
}

private struct SegmentLayout: Identifiable {
    let segment: DistributionSegment
    let xStart: CGFloat
    let width: CGFloat
    var id: String { segment.id }
}

private struct TopFaceShape: Shape {
    let depth: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 0, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.maxX - depth, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.maxX, y: 0))
        path.addLine(to: CGPoint(x: depth, y: 0))
        path.closeSubpath()
        return path
    }
}

private struct RightFaceShape: Shape {
    let depth: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 0, y: depth))
        path.addLine(to: CGPoint(x: rect.maxX, y: 0))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - depth))
        path.addLine(to: CGPoint(x: 0, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

private struct LegendRow: View {
    let segment: DistributionSegment
    let currencyCode: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4 * widthScale) {
            HStack {
                Text(segment.label)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                Spacer(minLength: 8 * widthScale)
                Text(segment.fraction.formatted(.percent.precision(.fractionLength(2))))
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            HStack {
                Text(L10n.Home.portfolioDistributionAmount)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoGreyContrast)
                Spacer(minLength: 8 * widthScale)
                Text(segment.amount.formatted(.currency(code: currencyCode).precision(.fractionLength(2))))
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
            .padding(.bottom, 6 * widthScale)
            Rectangle()
                .fill(segment.colorToken.color)
                .frame(height: 2 * widthScale)
                .accessibilityHidden(true)
        }
    }
}

#Preview("Single holding") {
    PortfolioDistributionCard(
        data: PortfolioDistributionData(
            totalValue: Decimal(string: "1084.92") ?? 0,
            currencyCode: "USD",
            segments: [
                DistributionSegment(
                    id: "cash",
                    label: "Cash",
                    fraction: 1.0,
                    amount: Decimal(string: "1084.92") ?? 0,
                    colorToken: .warning
                )
            ]
        )
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Multi holding") {
    PortfolioDistributionCard(
        data: PortfolioDistributionData(
            totalValue: Decimal(string: "12430.18") ?? 0,
            currencyCode: "USD",
            segments: [
                DistributionSegment(
                    id: "AAPL",
                    label: "AAPL",
                    fraction: 0.45,
                    amount: Decimal(string: "5593.58") ?? 0,
                    colorToken: .info
                ),
                DistributionSegment(
                    id: "AMD",
                    label: "AMD",
                    fraction: 0.30,
                    amount: Decimal(string: "3729.06") ?? 0,
                    colorToken: .avatarPurple
                ),
                DistributionSegment(
                    id: "NVDA",
                    label: "NVDA",
                    fraction: 0.15,
                    amount: Decimal(string: "1864.53") ?? 0,
                    colorToken: .positive
                ),
                DistributionSegment(
                    id: "cash",
                    label: "Cash",
                    fraction: 0.10,
                    amount: Decimal(string: "1243.02") ?? 0,
                    colorToken: .warning
                )
            ]
        )
    )
    .padding()
    .background(Color.sevinoPrimary)
}
