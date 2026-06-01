import SwiftUI

private typealias EndKind = RecurringInvestmentCardViewModel.EndKind

/// Chat gen-UI card for scheduling a recurring buy. Mirrors the
/// `TradeExecutionCard` chrome + hold-to-confirm gesture and layers recurrence
/// inputs on top: frequency, start date, and end condition.
struct RecurringInvestmentCard: View {
    let block: RecurringInvestmentSetupBlock
    @State private var model: RecurringInvestmentCardViewModel
    @State private var amountText: String
    @FocusState private var amountFocused: Bool
    let scale: CGFloat

    init(block: RecurringInvestmentSetupBlock, scale: CGFloat = 1) {
        self.block = block
        _model = State(initialValue: RecurringInvestmentCardViewModel(block: block))
        _amountText = State(initialValue: RecurringInvestmentCardViewModel.amountText(block.defaultAmount))
        self.scale = scale
    }

    #if DEBUG
    init(model: RecurringInvestmentCardViewModel, scale: CGFloat = 1) {
        self.block = model.block
        _model = State(initialValue: model)
        _amountText = State(initialValue: RecurringInvestmentCardViewModel.amountText(model.amount))
        self.scale = scale
    }
    #endif

    private var isLocked: Bool {
        model.state == .submitting || model.state == .scheduled
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18 * scale) {
            RecurringHeader(model: model, scale: scale)
            RecurringAssetRow(block: model.block, scale: scale)
            VStack(alignment: .leading, spacing: 18 * scale) {
                RecurringAmountSection(model: model, amountText: $amountText, amountFocused: $amountFocused, scale: scale)
                RecurringFrequencySection(model: model, scale: scale)
                RecurringStartsOnSection(model: model, scale: scale)
                RecurringEndsSection(model: model, scale: scale)
            }
            .disabled(isLocked)
            RecurringSummary(model: model, scale: scale)
            RecurringFooter(model: model, amountFocused: $amountFocused, scale: scale)
            RecurringDisclaimer(text: model.block.disclaimer)
        }
        .padding(16 * scale)
        .background(GenUICardBackground(cornerRadius: 20 * scale))
        .padding(.horizontal, 16 * scale)
        .animation(.spring(duration: 0.35, bounce: 0.15), value: model.state)
        .onChange(of: amountText) { _, newValue in
            model.updateAmount(from: newValue)
        }
        .onChange(of: block) { _, newBlock in
            model.block = newBlock
        }
    }
}

private struct RecurringHeader: View {
    let model: RecurringInvestmentCardViewModel
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Text(L10n.RecurringInvestment.header)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.sevinoInfo)
                .padding(.horizontal, 12 * scale)
                .padding(.vertical, 4 * scale)
                .background(
                    RoundedRectangle(cornerRadius: 8 * scale)
                        .fill(Color.sevinoInfo.opacity(0.18))
                )
            Spacer(minLength: 0)
            statusPill
        }
    }

    @ViewBuilder
    private var statusPill: some View {
        switch model.state {
        case .editing:
            EmptyView()
        case .submitting:
            ProgressView()
                .controlSize(.small)
                .accessibilityLabel(L10n.RecurringInvestment.scheduling)
        case .scheduled:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 18 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPositive)
                .accessibilityLabel(L10n.RecurringInvestment.scheduled)
        case .failed:
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 18 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityLabel(L10n.RecurringInvestment.scheduleFailed)
        }
    }
}

private struct RecurringAssetRow: View {
    let block: RecurringInvestmentSetupBlock
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 12 * scale) {
            StockLogoView(ticker: block.ticker, size: 40 * scale)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(block.companyName)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(L10n.TradeExecution.tickerExchangeFormat(block.ticker, block.exchange))
                    .font(.subheadline)
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct RecurringAmountSection: View {
    let model: RecurringInvestmentCardViewModel
    @Binding var amountText: String
    @FocusState.Binding var amountFocused: Bool
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            RecurringFieldLabel(L10n.RecurringInvestment.amountLabel, scale: scale)
            HStack(alignment: .firstTextBaseline, spacing: 2 * scale) {
                Text(verbatim: "$")
                    .font(.system(size: 30 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                TextField("", text: $amountText, prompt: Text(verbatim: "0"))
                    .font(.system(size: 44 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .keyboardType(.decimalPad)
                    .focused($amountFocused)
                    .fixedSize(horizontal: true, vertical: false)
                Spacer(minLength: 0)
            }
            Text(model.estimatedSharesSubline)
                .font(.subheadline)
                .foregroundStyle(Color.sevinoGreyContrast)
                .contentTransition(.numericText())
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(L10n.RecurringInvestment.amountLabel)
        .accessibilityValue(model.amount.asCurrency())
    }
}

private struct RecurringFrequencySection: View {
    @Bindable var model: RecurringInvestmentCardViewModel
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            RecurringFieldLabel(L10n.RecurringInvestment.frequencyLabel, scale: scale)
            Picker(L10n.RecurringInvestment.frequencyLabel, selection: $model.frequency) {
                Text(L10n.RecurringInvestment.daily).tag(RecurringFrequency.daily)
                Text(L10n.RecurringInvestment.weekly).tag(RecurringFrequency.weekly)
                Text(L10n.RecurringInvestment.biweekly).tag(RecurringFrequency.biweekly)
                Text(L10n.RecurringInvestment.monthly).tag(RecurringFrequency.monthly)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }
}

private struct RecurringStartsOnSection: View {
    @Bindable var model: RecurringInvestmentCardViewModel
    let scale: CGFloat

    var body: some View {
        HStack {
            RecurringFieldLabel(L10n.RecurringInvestment.startsOn, scale: scale)
            Spacer(minLength: 0)
            DatePicker(
                L10n.RecurringInvestment.startsOn,
                selection: $model.startDate,
                in: model.minStartDate...,
                displayedComponents: .date
            )
            .labelsHidden()
        }
    }
}

private struct RecurringEndsSection: View {
    @Bindable var model: RecurringInvestmentCardViewModel
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 10 * scale) {
            RecurringFieldLabel(L10n.RecurringInvestment.ends, scale: scale)
            Picker(L10n.RecurringInvestment.ends, selection: $model.endKind) {
                Text(L10n.RecurringInvestment.never).tag(EndKind.never)
                Text(L10n.RecurringInvestment.onDate).tag(EndKind.onDate)
                Text(L10n.RecurringInvestment.afterCount).tag(EndKind.afterCount)
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            switch model.endKind {
            case .never:
                EmptyView()
            case .onDate:
                HStack {
                    RecurringFieldLabel(L10n.RecurringInvestment.onDate, scale: scale)
                    Spacer(minLength: 0)
                    DatePicker(
                        L10n.RecurringInvestment.onDate,
                        selection: $model.endDate,
                        in: model.minEndDate...,
                        displayedComponents: .date
                    )
                    .labelsHidden()
                }
            case .afterCount:
                Stepper(value: $model.occurrenceCount, in: 1...999) {
                    Text(L10n.RecurringInvestment.occurrencesValue(model.occurrenceCount))
                        .font(.body)
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }
        }
    }
}

private struct RecurringSummary: View {
    let model: RecurringInvestmentCardViewModel
    let scale: CGFloat

    var body: some View {
        Text(model.summaryLine)
            .font(.subheadline.weight(.medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(12 * scale)
            .background(
                RoundedRectangle(cornerRadius: 12 * scale)
                    .fill(Color.sevinoSettingsBg)
            )
            .accessibilityElement(children: .combine)
    }
}

private struct RecurringFooter: View {
    let model: RecurringInvestmentCardViewModel
    @FocusState.Binding var amountFocused: Bool
    let scale: CGFloat

    var body: some View {
        switch model.state {
        case .editing, .failed:
            RecurringEditingFooter(model: model, amountFocused: $amountFocused, scale: scale)
        case .submitting:
            RecurringSubmittingButton(scale: scale)
        case .scheduled:
            RecurringScheduledReceipt(firstBuyOn: model.firstBuyOnText, scale: scale)
        }
    }
}

private struct RecurringEditingFooter: View {
    let model: RecurringInvestmentCardViewModel
    @FocusState.Binding var amountFocused: Bool
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 8 * scale) {
            if model.state == .failed, let error = model.error {
                RecurringBanner(text: error, systemImage: "exclamationmark.triangle.fill", color: .sevinoNegative, scale: scale)
            } else if let validation = model.validationMessage {
                Text(validation)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
            }
            HoldToConfirmButton(
                title: L10n.RecurringInvestment.holdToSchedule,
                isEnabled: model.isValid,
                scale: scale,
                accessibilityHint: L10n.RecurringInvestment.holdToScheduleA11yHint
            ) {
                amountFocused = false
                Task { await model.submit() }
            }
            if model.state == .failed {
                Text(L10n.RecurringInvestment.retry)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }
}

private struct RecurringSubmittingButton: View {
    let scale: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14 * scale)
                .fill(Color.sevinoPositive.opacity(0.45))
            ProgressView()
                .tint(.white)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 38 * scale)
        .accessibilityLabel(L10n.RecurringInvestment.scheduling)
    }
}

private struct RecurringScheduledReceipt: View {
    let firstBuyOn: String
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 10 * scale) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 20 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPositive)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(L10n.RecurringInvestment.scheduled)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                Text(firstBuyOn)
                    .font(.subheadline)
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
            Spacer(minLength: 0)
        }
        .padding(12 * scale)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 12 * scale)
                .fill(Color.sevinoPositive.opacity(0.12))
        )
        .accessibilityElement(children: .combine)
    }
}

private struct RecurringDisclaimer: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(Color.sevinoGreyContrast)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct RecurringFieldLabel: View {
    let text: String
    let scale: CGFloat

    init(_ text: String, scale: CGFloat) {
        self.text = text
        self.scale = scale
    }

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 11 * scale, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(Color.sevinoGreyContrast)
    }
}

private struct RecurringBanner: View {
    let text: String
    let systemImage: String
    let color: Color
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: systemImage)
                .font(.system(size: 13 * scale, weight: .semibold))
                .accessibilityHidden(true)
            Text(text)
                .font(.footnote.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .foregroundStyle(color)
        .padding(10 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10 * scale)
                .fill(color.opacity(0.12))
        )
    }
}

#if DEBUG
private func previewDate(addingDays days: Int) -> Date {
    Calendar.current.date(byAdding: .day, value: days, to: .now) ?? .now
}

private let previewAAPL = RecurringInvestmentSetupBlock(
    blockId: "blk_ri_aapl",
    ticker: "AAPL",
    companyName: "Apple Inc.",
    exchange: "NASDAQ",
    currentPrice: 195.20,
    defaultAmount: 200,
    defaultFrequency: .biweekly,
    defaultStartDate: previewDate(addingDays: 3),
    defaultEndCondition: .never,
    disclaimer: "Recurring buys place a market order at the next open on each scheduled date. You can cancel anytime."
)

private let previewVOO = RecurringInvestmentSetupBlock(
    blockId: "blk_ri_voo",
    ticker: "VOO",
    companyName: "Vanguard S&P 500 ETF",
    exchange: "NYSE",
    currentPrice: 512.74,
    defaultAmount: 500,
    defaultFrequency: .monthly,
    defaultStartDate: previewDate(addingDays: 10),
    defaultEndCondition: .afterCount(24),
    disclaimer: "Recurring buys place a market order at the next open on each scheduled date. You can cancel anytime."
)

#Preview("Editing · AAPL biweekly") {
    ScrollView {
        RecurringInvestmentCard(block: previewAAPL)
            .padding(.vertical, 16)
    }
    .background(Color.sevinoPrimary.ignoresSafeArea())
    .preferredColorScheme(.dark)
}

#Preview("Editing · VOO monthly ×24") {
    ScrollView {
        RecurringInvestmentCard(block: previewVOO)
            .padding(.vertical, 16)
    }
    .background(Color.sevinoPrimary.ignoresSafeArea())
    .preferredColorScheme(.light)
}

#Preview("Scheduled receipt") {
    ScrollView {
        RecurringInvestmentCard(model: .previewModel(block: previewVOO, state: .scheduled))
            .padding(.vertical, 16)
    }
    .background(Color.sevinoPrimary.ignoresSafeArea())
    .preferredColorScheme(.dark)
}

#Preview("Failed") {
    ScrollView {
        RecurringInvestmentCard(
            model: .previewModel(
                block: previewAAPL,
                state: .failed,
                error: "Couldn't reach the scheduler. Check your connection and try again."
            )
        )
        .padding(.vertical, 16)
    }
    .background(Color.sevinoPrimary.ignoresSafeArea())
    .preferredColorScheme(.dark)
}
#endif
