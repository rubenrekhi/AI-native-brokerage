import QuickLook
import SwiftUI

struct DocumentsListView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    let title: String

    @State private var viewModel: DocumentsViewModel
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    init(title: String, documentType: String?) {
        self.title = title
        _viewModel = State(initialValue: DocumentsViewModel(documentType: documentType))
    }

    init(title: String, viewModel: DocumentsViewModel) {
        self.title = title
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                SettingsHeaderView(title: title, scale: scale, onBack: { dismiss() })
                    .padding(.bottom, 24 * scale)

                content
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
        .navigationBarBackButtonHidden()
        .task { await loadIfNeeded() }
        .quickLookPreview(viewModel.previewBinding)
        .alert(
            L10n.Settings.documentDownloadErrorTitle,
            isPresented: viewModel.showDownloadErrorBinding,
            presenting: viewModel.downloadError
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: viewModel.clearDownloadError)
        } message: { message in
            Text(message)
        }
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.documents.isEmpty {
            DocumentsLoadingState(scale: scale)
        } else if let error = viewModel.error, viewModel.documents.isEmpty {
            DocumentsErrorState(message: error, scale: scale, onRetry: reload)
        } else if viewModel.documents.isEmpty {
            DocumentsEmptyState()
        } else {
            list
        }
    }

    private var list: some View {
        VStack(spacing: 0) {
            ForEach(viewModel.documents) { doc in
                DocumentRow(
                    document: doc,
                    scale: scale,
                    isDownloading: viewModel.downloadingDocumentId == doc.id,
                    isDisabled: viewModel.downloadingDocumentId != nil
                        && viewModel.downloadingDocumentId != doc.id,
                    onTap: { open(doc) }
                )
            }
        }
    }

    private func loadIfNeeded() async {
        if viewModel.documents.isEmpty { await viewModel.load() }
    }

    private func reload() {
        Task { await viewModel.reload() }
    }

    private func open(_ document: DocumentDTO) {
        Task { await viewModel.openDocument(document) }
    }
}

private struct DocumentsLoadingState: View {
    let scale: CGFloat

    var body: some View {
        ProgressView()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 32 * scale)
    }
}

private struct DocumentsErrorState: View {
    let message: String
    let scale: CGFloat
    let onRetry: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label(L10n.Settings.loadErrorTitle, systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button(L10n.Settings.loadErrorRetry, action: onRetry)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 10 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 20 * scale))
        }
        .frame(maxWidth: .infinity)
    }
}

private struct DocumentsEmptyState: View {
    var body: some View {
        ContentUnavailableView {
            Label(L10n.Settings.documentsEmptyTitle, systemImage: "doc.text")
        } description: {
            Text(L10n.Settings.documentsEmptyMessage)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct DocumentRow: View {
    let document: DocumentDTO
    let scale: CGFloat
    let isDownloading: Bool
    let isDisabled: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 0) {
                HStack(spacing: 12 * scale) {
                    Image(systemName: "doc.text")
                        .font(.system(size: 18 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(width: 28 * scale)
                        .accessibilityHidden(true)

                    VStack(alignment: .leading, spacing: 2 * scale) {
                        Text(document.displayTitle)
                            .font(.system(size: 16 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)

                        Text(document.displayDate)
                            .font(.system(size: 12 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)
                    }

                    Spacer()

                    if isDownloading {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .accessibilityHidden(true)
                    }
                }
                .padding(.vertical, 14 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
            .contentShape(Rectangle())
            .frame(minHeight: 44)
        }
        .disabled(isDisabled || isDownloading)
        .opacity(isDisabled ? 0.5 : 1)
        .accessibilityLabel(Text("\(document.displayTitle), \(document.displayDate)"))
        .accessibilityHint(Text(L10n.Settings.documentRowAccessibilityHint))
        .accessibilityValue(isDownloading ? Text(L10n.Settings.documentRowLoading) : Text(""))
    }
}

#Preview("Dark") {
    NavigationStack {
        DocumentsListView(title: "Account documents", documentType: nil)
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        DocumentsListView(title: "Account documents", documentType: nil)
    }
    .preferredColorScheme(.light)
}
