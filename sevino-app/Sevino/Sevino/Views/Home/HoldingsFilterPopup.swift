import SwiftUI

struct HoldingsFilterPopup: View {
    let scale: CGFloat
    let displayOption: HoldingsDisplayOption
    let sortOption: HoldingsSortOption
    let onSelectDisplay: (HoldingsDisplayOption) -> Void
    let onSelectSort: (HoldingsSortOption) -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Home.filterDisplayBy)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .padding(.bottom, 6 * scale)

            ForEach(HoldingsDisplayOption.allCases) { option in
                filterRow(label: option.label, isSelected: option == displayOption) {
                    onSelectDisplay(option)
                    onDismiss()
                }
            }

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
                .padding(.vertical, 8 * scale)

            Text(L10n.Home.filterSortBy)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .padding(.bottom, 6 * scale)

            ForEach(HoldingsSortOption.allCases) { option in
                filterRow(label: option.label, isSelected: option == sortOption) {
                    onSelectSort(option)
                    onDismiss()
                }
            }
        }
        .padding(12 * scale)
        .frame(width: 180 * scale)
        .background(Color.sevinoSettingsContrast, in: .rect(cornerRadius: 16 * scale))
        .shadow(color: Color.sevinoPrimary.opacity(0.3), radius: 12, y: 4)
    }

    private func filterRow(label: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(label)
                    .font(.system(size: 13 * scale, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(isSelected ? Color.sevinoSecondary : Color.sevinoGreyContrast)
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }
            .padding(.vertical, 6 * scale)
            .contentShape(.rect)
        }
    }
}
