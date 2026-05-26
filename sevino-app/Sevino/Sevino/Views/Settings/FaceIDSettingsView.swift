import SwiftUI

struct FaceIDSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var viewModel = FaceIDViewModel()
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            content

            Spacer()
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 12 * scale)
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .navigationBarBackButtonHidden()
        .task {
            viewModel.checkAvailability()
        }
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.manageFaceId, scale: scale, onBack: { dismiss() })
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isFaceIDAvailable, let label = viewModel.biometricTypeLabel {
            toggleRow(label: label)
            Text(L10n.Settings.biometricToggleHelper(label))
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 8 * scale)
        } else {
            unavailableCard
        }
    }

    private func toggleRow(label: String) -> some View {
        VStack(spacing: 0) {
            Toggle(isOn: $viewModel.isEnabled) {
                Text(label)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            .tint(.green)
            .disabled(viewModel.isAuthenticating)
            .onChange(of: viewModel.isEnabled) { oldValue, newValue in
                guard newValue, !oldValue else { return }
                Task { await viewModel.confirmEnable() }
            }
            .padding(.vertical, 16 * scale)

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
    }

    private var unavailableCard: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(L10n.Settings.biometricsUnavailableTitle)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            Text(L10n.Settings.biometricsUnavailableMessage)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }
}

#Preview("Dark") {
    NavigationStack {
        FaceIDSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        FaceIDSettingsView()
    }
    .preferredColorScheme(.light)
}
