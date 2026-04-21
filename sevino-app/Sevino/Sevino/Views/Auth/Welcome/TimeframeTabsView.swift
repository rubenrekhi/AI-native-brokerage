import SwiftUI

struct TimeframeTabsView: View {
    let scale: CGFloat
    let selected: Timeframe

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Timeframe.allCases) { tf in
                let isSelected = tf == selected
                Text(tf.rawValue)
                    .font(.system(size: 11 * scale, weight: isSelected ? .bold : .regular))
                    .foregroundStyle(isSelected ? Color.welcomeText : Color.welcomeTextDimmed)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6 * scale)
                    .modifier(SevinoGlass.conditionalChip(isSelected: isSelected))
            }
        }
    }
}
