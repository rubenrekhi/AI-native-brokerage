import SwiftUI

struct OnboardingCompoundView: View {
    let scale: CGFloat
    let years: Int
    let animate: Bool
    let onContinue: () -> Void

    @State private var barProgress: CGFloat = 0
    @State private var displayedStart: Double = 0
    @State private var displayedWait: Double = 0
    @State private var displayedSavings: Double = 0


    private var startTodayValue: Double { futureValue(rate: 0.10, years: years) }
    private var wait5Value: Double { futureValue(rate: 0.10, years: max(years - 5, 0)) }
    private var savingsValue: Double { futureValue(rate: 0.005, years: years) }
    private var difference: Double { startTodayValue - wait5Value }

    private func futureValue(rate: Double, years: Int) -> Double {
        guard years > 0 else { return 0 }
        let monthlyRate = rate / 12.0
        let months = Double(years * 12)
        return 500.0 * (pow(1 + monthlyRate, months) - 1) / monthlyRate
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 24 * scale) {
                    Text(L10n.Onboarding.compoundHeading(years))
                        .font(.system(size: 26 * scale, weight: .light))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20 * scale)

                    chartCard

                    legendSection

                    motivationText
                }
                .padding(.top, 20 * scale)
                .padding(.bottom, 60 * scale)
            }
            .scrollIndicators(.hidden)

            Button(action: onContinue) {
                Text(L10n.Onboarding.setupAccount)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(Color.welcomeText)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14 * scale)
            }
            .buttonStyle(.plain)
            .modifier(SevinoGlass.tintedButton(tint: Color.onboardingButtonActive))
            .padding(.horizontal, 32 * scale)
            .padding(.bottom, 16 * scale)
        }
        .task { await runAnimations() }
    }


    private var chartCard: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                HStack(alignment: .bottom, spacing: 0) {
                    yAxis
                    barsArea
                }
                .frame(height: 200 * scale)
                .padding(.top, 20 * scale)
                .padding(.leading, 12 * scale)
                .padding(.trailing, 4 * scale)

                xAxisLabels
                    .padding(.top, 8 * scale)
                    .padding(.bottom, 12 * scale)
            }
            .modifier(SevinoGlass.nav)
        }
        .padding(.horizontal, 20 * scale)
    }

    private var yAxis: some View {
        let maxVal = ceilToNice(startTodayValue)
        let steps = 5
        return VStack(alignment: .trailing, spacing: 0) {
            ForEach((0...steps).reversed(), id: \.self) { i in
                Text(formatShort(maxVal * Double(i) / Double(steps)))
                    .font(.system(size: 10 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                if i > 0 { Spacer(minLength: 0) }
            }
        }
        .frame(width: 50 * scale)
    }

    private var barsArea: some View {
        let maxVal = ceilToNice(startTodayValue)
        return GeometryReader { geo in
            HStack(alignment: .bottom, spacing: 24 * scale) {
                Spacer(minLength: 0)
                barView(value: savingsValue, maxVal: maxVal, height: geo.size.height, color: Color.onboardingChartSavings)
                barView(value: wait5Value, maxVal: maxVal, height: geo.size.height, color: Color.onboardingChartWait)
                barView(value: startTodayValue, maxVal: maxVal, height: geo.size.height, color: Color.onboardingChartStart)
                Spacer(minLength: 0)
            }
        }
    }

    private func barView(value: Double, maxVal: Double, height: CGFloat, color: Color) -> some View {
        let ratio = maxVal > 0 ? CGFloat(value / maxVal) : 0
        let barHeight = max(height * ratio * barProgress, 2 * scale)
        return VStack {
            Spacer(minLength: 0)
            RoundedRectangle(cornerRadius: 4 * scale)
                .fill(color)
                .frame(width: 56 * scale, height: barHeight)
        }
    }

    private var xAxisLabels: some View {
        HStack {
            Spacer()
                .frame(width: 50 * scale)
            HStack(spacing: 24 * scale) {
                Spacer(minLength: 0)
                Text(L10n.Onboarding.compoundChartSavings)
                    .frame(width: 56 * scale)
                Text(L10n.Onboarding.compoundChartWait)
                    .frame(width: 56 * scale)
                Text(L10n.Onboarding.compoundChartStart)
                    .frame(width: 56 * scale)
                Spacer(minLength: 0)
            }
            .font(.system(size: 9 * scale))
            .foregroundStyle(Color.welcomeTextDimmed)
            .multilineTextAlignment(.center)
        }
    }


    private var legendSection: some View {
        VStack(spacing: 20 * scale) {
            legendRow(color: .onboardingChartStart, label: L10n.Onboarding.compoundLegendStart, value: displayedStart, valueColor: .onboardingChartStart)
            legendRow(color: .onboardingChartWait, label: L10n.Onboarding.compoundLegendWait, value: displayedWait, valueColor: .onboardingChartWait)
            legendRow(color: .onboardingChartSavings, label: L10n.Onboarding.compoundLegendSavings, value: displayedSavings, valueColor: .onboardingChartSavings)
        }
        .padding(.horizontal, 20 * scale)
    }

    private func legendRow(color: Color, label: String, value: Double, valueColor: Color) -> some View {
        HStack {
            Circle()
                .fill(color)
                .frame(width: 8 * scale, height: 8 * scale)
            Text(label)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)
            Spacer()
            Text(formatFull(value))
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(valueColor)
                .monospacedDigit()
        }
    }


    private var motivationText: some View {
        VStack(spacing: 4 * scale) {
            Text(L10n.Onboarding.compoundMotivation1(formatFull(difference)))
            Text(L10n.Onboarding.compoundMotivation2)
            Text(L10n.Onboarding.compoundMotivation3)
        }
        .font(.system(size: 16 * scale))
        .foregroundStyle(Color.welcomeTextSecondary)
        .multilineTextAlignment(.center)
        .padding(.horizontal, 20 * scale)
    }


    private func formatShort(_ value: Double) -> String {
        if value >= 1_000_000 {
            let m = value / 1_000_000
            return m == m.rounded() ? String(format: "$%.0fM", m) : String(format: "$%.1fM", m)
        } else if value >= 1000 {
            return String(format: "$%.0fK", value / 1000)
        }
        return String(format: "$%.0f", value)
    }

    private static let currencyFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.maximumFractionDigits = 0
        return f
    }()

    private func formatFull(_ value: Double) -> String {
        Self.currencyFormatter.string(from: NSNumber(value: value)) ?? "$0"
    }

    private func ceilToNice(_ value: Double) -> Double {
        let magnitude = pow(10, floor(log10(value)))
        return ceil(value / (magnitude / 2)) * (magnitude / 2)
    }


    private func runAnimations() async {
        guard animate else {
            barProgress = 1
            displayedStart = startTodayValue
            displayedWait = wait5Value
            displayedSavings = savingsValue
            return
        }

        try? await Task.sleep(for: .milliseconds(600))

        withAnimation(.easeOut(duration: 1.2)) { barProgress = 1 }

        try? await Task.sleep(for: .milliseconds(400))

        let totalSteps = 60
        for step in 1...totalSteps {
            let t = Double(step) / Double(totalSteps)
            let eased = 1 - pow(1 - t, 3)
            displayedStart = startTodayValue * eased
            displayedWait = wait5Value * eased
            displayedSavings = savingsValue * eased
            try? await Task.sleep(for: .milliseconds(25))
        }
        displayedStart = startTodayValue
        displayedWait = wait5Value
        displayedSavings = savingsValue
    }
}

#Preview {
    OnboardingCompoundView(scale: 1, years: 43, animate: true, onContinue: {})
        .background(Color.black)
        .preferredColorScheme(.dark)
}
