import SwiftUI

/// A segment of a chat message — either plain text or a ticker symbol rendered inline as a pill.
enum MessageSegment: Equatable, Hashable {
    case text(String)
    case ticker(String)
}

/// Renders a message with inline ticker tokens styled as Slack-like pills.
///
/// Text segments are split at whitespace so surrounding words wrap naturally around the pills.
/// Pills use `Color.sevinoHighlightText` on `Color.sevinoHighlightBg` with rounded corners.
struct TickerTokenText: View {
    private let tokens: [TokenItem]

    init(segments: [MessageSegment]) {
        self.tokens = Self.buildTokens(from: segments)
    }

    var body: some View {
        TickerFlowLayout(horizontalSpacing: 4, verticalSpacing: 4) {
            ForEach(tokens) { item in
                switch item.token {
                case .word(let word):
                    Text(word)
                case .ticker(let symbol):
                    TickerPill(symbol: symbol)
                }
            }
        }
    }

    static func buildTokens(from segments: [MessageSegment]) -> [TokenItem] {
        var id = 0
        return segments.flatMap { segment -> [TokenItem] in
            switch segment {
            case .text(let string):
                return string
                    .split(whereSeparator: \.isWhitespace)
                    .map { word in
                        defer { id += 1 }
                        return TokenItem(id: id, token: .word(String(word)))
                    }
            case .ticker(let symbol):
                defer { id += 1 }
                return [TokenItem(id: id, token: .ticker(symbol))]
            }
        }
    }

    struct TokenItem: Identifiable, Equatable {
        let id: Int
        let token: Token
    }

    enum Token: Equatable {
        case word(String)
        case ticker(String)
    }
}

private struct TickerPill: View {
    let symbol: String

    var body: some View {
        Text(symbol)
            .fontWeight(.semibold)
            .foregroundStyle(Color.sevinoHighlightText)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Color.sevinoHighlightBg, in: .rect(cornerRadius: 6))
    }
}

/// Wrapping horizontal layout: items flow left-to-right and break to a new line when they
/// would exceed the proposed width. Items on the same line are centered vertically.
private struct TickerFlowLayout: Layout {
    var horizontalSpacing: CGFloat
    var verticalSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = computeRows(maxWidth: proposal.width ?? .infinity, subviews: subviews)
        let width = rows.map(\.width).max() ?? 0
        let height = rows.reduce(0) { $0 + $1.height }
            + CGFloat(max(0, rows.count - 1)) * verticalSpacing
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = computeRows(maxWidth: bounds.width, subviews: subviews)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(
                    at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(size)
                )
                x += size.width + horizontalSpacing
            }
            y += row.height + verticalSpacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func computeRows(maxWidth: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var current = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let projectedWidth = current.indices.isEmpty
                ? size.width
                : current.width + horizontalSpacing + size.width
            if projectedWidth > maxWidth, !current.indices.isEmpty {
                rows.append(current)
                current = Row(indices: [index], width: size.width, height: size.height)
            } else {
                current.indices.append(index)
                current.width = projectedWidth
                current.height = max(current.height, size.height)
            }
        }
        if !current.indices.isEmpty {
            rows.append(current)
        }
        return rows
    }
}

#Preview("Multiple tickers") {
    TickerTokenText(segments: [
        .text("Buy $20 of "),
        .ticker("TSLA"),
        .text(" and 2 shares of "),
        .ticker("AMD"),
    ])
    .foregroundStyle(Color.sevinoSecondary)
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Single ticker") {
    TickerTokenText(segments: [
        .text("Show me "),
        .ticker("AAPL"),
        .text(" performance"),
    ])
    .foregroundStyle(Color.sevinoSecondary)
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("No tickers") {
    TickerTokenText(segments: [
        .text("How is my portfolio doing today?")
    ])
    .foregroundStyle(Color.sevinoSecondary)
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Leads with ticker") {
    TickerTokenText(segments: [
        .ticker("NVDA"),
        .text(" is up 3% this week"),
    ])
    .foregroundStyle(Color.sevinoSecondary)
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Wraps onto multiple lines") {
    TickerTokenText(segments: [
        .text("Compare "),
        .ticker("AAPL"),
        .text(" "),
        .ticker("MSFT"),
        .text(" "),
        .ticker("GOOGL"),
        .text(" "),
        .ticker("AMZN"),
        .text(" "),
        .ticker("META"),
        .text(" over the past quarter"),
    ])
    .foregroundStyle(Color.sevinoSecondary)
    .padding()
    .frame(width: 260)
    .background(Color.sevinoPrimary)
}
