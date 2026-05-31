import SwiftUI

struct FilterMenu<Picker: View>: View {
    let label: String
    let selectionLabel: String
    let isActive: Bool
    let scale: CGFloat
    @ViewBuilder let picker: () -> Picker

    var body: some View {
        Menu {
            picker()
        } label: {
            HStack(spacing: 4 * scale) {
                Text(isActive ? selectionLabel : label)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(isActive ? Color.sevinoSecondary : Color.sevinoGreyContrast)

                Image(systemName: "chevron.down")
                    .font(.system(size: 10 * scale, weight: .semibold))
                    .foregroundStyle(isActive ? Color.sevinoSecondary : Color.sevinoGreyContrast)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 8 * scale)
            .frame(minHeight: 32 * scale)
            .modifier(SevinoGlass.chip)
        }
    }
}
