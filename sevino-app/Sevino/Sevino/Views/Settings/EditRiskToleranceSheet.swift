import SwiftUI

/// Read-only sheet that shows the user's derived risk tolerance alongside the
/// underlying onboarding responses it was computed from. Re-answering the risk
/// questions is not supported yet.
struct EditRiskToleranceSheet: View {
    let riskTolerance: String
    let maxLossTolerance: String?
    let riskScenarioResponse: String?

    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                toleranceCard
                    .padding(.bottom, 16 * scale)

                if hasUnderlyingValues {
                    underlyingValuesCard
                        .padding(.bottom, 16 * scale)
                }

                Text(L10n.Settings.editRiskToleranceDerivation)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Spacer()
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
    }

    private var hasUnderlyingValues: Bool {
        !(maxLossTolerance ?? "").isEmpty || !(riskScenarioResponse ?? "").isEmpty
    }

    private var header: some View {
        ZStack {
            Text(L10n.Settings.editRiskToleranceTitle)
                .font(.system(size: 20 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack {
                Spacer()

                Button(L10n.Settings.editSheetDone) { dismiss() }
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .contentShape(Rectangle())
                    .frame(minWidth: 44, minHeight: 44)
                    .accessibilityLabel(L10n.Settings.editSheetCloseAccessibility)
            }
        }
    }

    private var toleranceCard: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(L10n.Settings.riskTolerance)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(riskTolerance)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }

    private var underlyingValuesCard: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            if let maxLoss = maxLossTolerance, !maxLoss.isEmpty {
                underlyingRow(label: L10n.Settings.editRiskToleranceMaxLossLabel, value: maxLoss)
            }

            if let scenario = riskScenarioResponse, !scenario.isEmpty {
                underlyingRow(label: L10n.Settings.editRiskToleranceScenarioLabel, value: scenario)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }

    private func underlyingRow(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(label)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(value)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#if DEBUG
#Preview("Aggressive + details") {
    EditRiskToleranceSheet(
        riskTolerance: L10n.Settings.riskAggressive,
        maxLossTolerance: "40%+",
        riskScenarioResponse: "buy_more"
    )
    .preferredColorScheme(.dark)
}

#Preview("Missing details") {
    EditRiskToleranceSheet(
        riskTolerance: L10n.Settings.missingValuePlaceholder,
        maxLossTolerance: nil,
        riskScenarioResponse: nil
    )
    .preferredColorScheme(.dark)
}
#endif
