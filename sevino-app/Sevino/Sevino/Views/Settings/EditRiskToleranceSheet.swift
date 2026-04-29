import SwiftUI

/// Read-only popup that shows the user's derived risk tolerance alongside the
/// underlying onboarding responses it was computed from. Re-answering the risk
/// questions is not supported yet, so the popup omits the Save action.
struct EditRiskToleranceSheet: View {
    let riskTolerance: String
    let maxLossTolerance: String?
    let riskScenarioResponse: String?

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    private var hasUnderlyingValues: Bool {
        !(maxLossTolerance ?? "").isEmpty || !(riskScenarioResponse ?? "").isEmpty
    }

    var body: some View {
        SettingsEditPopup(
            title: L10n.Settings.editRiskToleranceTitle,
            scale: scale,
            saveAction: nil
        ) {
            SettingsEditPopupSection(label: L10n.Settings.riskTolerance, scale: scale) {
                SettingsEditPopupReadOnlyValue(value: riskTolerance, scale: scale)
            }

            if let maxLoss = maxLossTolerance, !maxLoss.isEmpty {
                SettingsEditPopupSection(label: L10n.Settings.editRiskToleranceMaxLossLabel, scale: scale) {
                    SettingsEditPopupReadOnlyValue(value: maxLoss, scale: scale)
                }
            }

            if let scenario = riskScenarioResponse, !scenario.isEmpty {
                SettingsEditPopupSection(label: L10n.Settings.editRiskToleranceScenarioLabel, scale: scale) {
                    SettingsEditPopupReadOnlyValue(value: scenario, scale: scale)
                }
            }

            SettingsEditPopupHelperText(text: L10n.Settings.editRiskToleranceDerivation, scale: scale)
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
    }
}

#if DEBUG
#Preview("Aggressive + details") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditRiskToleranceSheet(
                riskTolerance: L10n.Settings.riskAggressive,
                maxLossTolerance: "40%+",
                riskScenarioResponse: "buy_more"
            )
        }
        .preferredColorScheme(.dark)
}

#Preview("Missing details") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditRiskToleranceSheet(
                riskTolerance: L10n.Settings.missingValuePlaceholder,
                maxLossTolerance: nil,
                riskScenarioResponse: nil
            )
        }
        .preferredColorScheme(.dark)
}
#endif
