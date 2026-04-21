import SwiftUI

struct RequirementTagView: View {
    let label: String
    let met: Bool
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 4 * scale) {
            Image(systemName: met ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 10 * scale))
            Text(label)
                .font(.system(size: 12 * scale))
        }
        .foregroundStyle(met ? Color.sevinoPositive : Color.sevinoNegative)
    }
}

#Preview {
    VStack(spacing: 12) {
        RequirementTagView(label: "Contains @", met: true, scale: 1)
        RequirementTagView(label: "Valid domain", met: false, scale: 1)
    }
    .padding()
    .preferredColorScheme(.dark)
}
