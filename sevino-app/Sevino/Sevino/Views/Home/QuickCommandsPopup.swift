import SwiftUI

struct QuickCommandsPopup: View {
    let scale: CGFloat
    @Binding var webSearchEnabled: Bool
    let bottomSafeArea: CGFloat
    let onDiscover: () -> Void
    let onDismiss: () -> Void

    private static let horizontalPadding: CGFloat = 20
    private static let rowVerticalPadding: CGFloat = 14
    private static let iconSize: CGFloat = 22
    private static let iconTrailingSpacing: CGFloat = 16
    private static let topCornerRadius: CGFloat = 28
    private static let closeButtonSize: CGFloat = 40
    private static let dismissThreshold: CGFloat = 60
    private static let contentBottomSpacing: CGFloat = 14

    @State private var dragOffset: CGFloat = 0

    private var backgroundShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: Self.topCornerRadius,
            bottomLeadingRadius: 55,
            bottomTrailingRadius: 55,
            topTrailingRadius: Self.topCornerRadius
        )
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                dragHandle
                    .gesture(dismissDragGesture)

                header

                row(
                    icon: "globe",
                    label: L10n.Home.quickCommandsAllowWebSearch
                ) {
                    Toggle("", isOn: $webSearchEnabled)
                        .labelsHidden()
                        .tint(.green)
                        .scaleEffect(scale)
                }

                Divider()
                    .foregroundStyle(Color.homePopupDivider)
                    .padding(.horizontal, Self.horizontalPadding * scale)

                Button(action: onDiscover) {
                    row(
                        icon: "plus.magnifyingglass",
                        label: L10n.Home.quickCommandsDiscover
                    ) { EmptyView() }
                }
                .buttonStyle(.plain)
            }
            .padding(.bottom, bottomSafeArea + Self.contentBottomSpacing * scale)
            .frame(maxWidth: .infinity)
            .modifier(SevinoGlass.sheet(shape: backgroundShape))
        }
        .offset(y: dragOffset)
    }

    private var dragHandle: some View {
        Capsule()
            .fill(Color.homeDragHandle)
            .frame(width: 40 * scale, height: 5 * scale)
            .frame(maxWidth: .infinity)
            .padding(.top, 10 * scale)
            .padding(.bottom, 4 * scale)
            .contentShape(.rect)
            .accessibilityHidden(true)
    }

    private var dismissDragGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                dragOffset = max(0, value.translation.height)
            }
            .onEnded { value in
                if value.translation.height > Self.dismissThreshold
                    || value.predictedEndTranslation.height > Self.dismissThreshold * 2 {
                    onDismiss()
                }
                withAnimation(.spring(duration: 0.25, bounce: 0.15)) {
                    dragOffset = 0
                }
            }
    }

    private var header: some View {
        Text(L10n.Home.quickCommandsTitle)
            .font(.system(size: 17 * scale, weight: .semibold))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 16 * scale)
            .padding(.top, 12 * scale)
            .padding(.bottom, 16 * scale)
    }

    private func row<Trailing: View>(
        icon: String,
        label: String,
        @ViewBuilder trailing: () -> Trailing
    ) -> some View {
        HStack(spacing: Self.iconTrailingSpacing * scale) {
            Image(systemName: icon)
                .font(.system(size: Self.iconSize * scale, weight: .regular))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: Self.iconSize * scale, height: Self.iconSize * scale)

            Text(label)
                .font(.system(size: 17 * scale))
                .foregroundStyle(Color.sevinoSecondary)

            Spacer(minLength: 0)

            trailing()
        }
        .padding(.horizontal, Self.horizontalPadding * scale)
        .padding(.vertical, Self.rowVerticalPadding * scale)
        .contentShape(.rect)
    }
}

#Preview("Dark") {
    VStack {
        Spacer()
        QuickCommandsPopup(
            scale: 1,
            webSearchEnabled: .constant(true),
            bottomSafeArea: 34,
            onDiscover: {},
            onDismiss: {}
        )
        .frame(height: 260)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    VStack {
        Spacer()
        QuickCommandsPopup(
            scale: 1,
            webSearchEnabled: .constant(false),
            bottomSafeArea: 34,
            onDiscover: {},
            onDismiss: {}
        )
        .frame(height: 260)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.light)
}
