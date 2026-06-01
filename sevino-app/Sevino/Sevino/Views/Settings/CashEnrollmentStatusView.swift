import SwiftUI

struct CashEnrollmentStatusView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var viewModel: CashEnrollmentStatusViewModel
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    init(viewModel: CashEnrollmentStatusViewModel = CashEnrollmentStatusViewModel()) {
        _viewModel = State(initialValue: viewModel)
    }

    private var apyText: String {
        viewModel.apy.formatted(.percent.precision(.fractionLength(2)))
    }

    private var enrolledDateText: String? {
        viewModel.sweepEnrolledAt?.formatted(.dateTime.month(.abbreviated).day().year())
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                VStack(alignment: .leading, spacing: 20 * scale) {
                    intro

                    EnrollmentStatusPill(state: viewModel.state, apyText: apyText, size: .large, scale: scale)
                        .frame(maxWidth: .infinity)

                    if viewModel.state != .unavailable && hasDetailRows {
                        detailRows
                    }
                }

                Spacer()

                if let error = viewModel.error {
                    errorBanner(error)
                        .padding(.bottom, 12 * scale)
                }

                actionSection
                    .padding(.bottom, 16 * scale)
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
        .task { await viewModel.load() }
    }

    private var header: some View {
        ZStack {
            Text(L10n.CashEnrollmentStatus.title)
                .font(.system(size: 20 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack {
                Button(L10n.Settings.backAccessibility, systemImage: "chevron.left", action: { dismiss() })
                    .labelStyle(.iconOnly)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)

                Spacer()

                Button(L10n.CashEnrollmentStatus.refreshAccessibility, systemImage: "arrow.clockwise", action: refresh)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)
                    .disabled(viewModel.isLoading || viewModel.isEnrolling)
            }
        }
    }

    private var intro: some View {
        Text(L10n.CashEnrollmentStatus.intro)
            .font(.system(size: 14 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var detailRows: some View {
        VStack(spacing: 0) {
            if let enrolledDateText {
                detailRow(label: dateLabel, value: enrolledDateText, isLast: !showApyRow)
            }
            if showApyRow {
                detailRow(label: apyLabel, value: apyText, isLast: true)
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private var showApyRow: Bool { viewModel.apy > 0 }
    private var hasDetailRows: Bool { enrolledDateText != nil || showApyRow }

    private var dateLabel: String {
        viewModel.state == .notEnrolled
            ? L10n.CashEnrollmentStatus.lastAttempt
            : L10n.CashEnrollmentStatus.enrolledSince
    }

    private var apyLabel: String {
        viewModel.state == .active
            ? L10n.CashEnrollmentStatus.currentApy
            : L10n.CashEnrollmentStatus.potentialApy
    }

    private func detailRow(label: String, value: String, isLast: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(label)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                Spacer()
                Text(value)
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            .padding(.vertical, 10 * scale)

            if !isLast {
                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    @ViewBuilder
    private var actionSection: some View {
        switch viewModel.state {
        case .notEnrolled:
            Button(action: reenroll) {
                Text(L10n.CashEnrollmentStatus.reenroll)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoPrimary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16 * scale)
                    .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))
            }
            .disabled(viewModel.isEnrolling)
        case .pending:
            VStack(spacing: 8 * scale) {
                HStack(spacing: 8 * scale) {
                    ProgressView()
                        .tint(Color.sevinoSecondary)
                    Text(L10n.CashEnrollmentStatus.enrollmentInProgress)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .rect(cornerRadius: 14 * scale))

                Text(L10n.CashEnrollmentStatus.pendingHint)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .multilineTextAlignment(.center)
            }
        case .active, .unavailable:
            EmptyView()
        }
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityHidden(true)
            Text(message)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12 * scale)
        .background(Color.sevinoNegative.opacity(0.12), in: .rect(cornerRadius: 12 * scale))
        .accessibilityElement(children: .combine)
    }

    private func refresh() {
        Task { await viewModel.load() }
    }

    private func reenroll() {
        Task { await viewModel.reenroll() }
    }
}

#if DEBUG
private struct PreviewFundingService: FundingServiceProtocol {
    var state: EnrollmentState = .notEnrolled
    var apy: String = "0.0425"
    var enrolledSince: String? = "2025-10-01T00:00:00+00:00"
    var failure: Error?

    func getCashInterest() async throws -> CashInterestResponse {
        if let failure { throw failure }
        return CashInterestResponse(
            balance: "2412.08",
            apy: apy,
            thisMonthEarned: "6.43",
            daysAccrued: 22,
            lifetimeEarned: "41.87",
            lifetimeSince: enrolledSince,
            buyingPower: "2412.08",
            pendingDeposits: "0",
            interestPaidOut: "monthly",
            fdicInsuredLimit: "2500000",
            sweepStatus: nil,
            enrollmentState: state
        )
    }

    func enrollCashInterest() async throws -> CashInterestResponse {
        try await getCashInterest()
    }

    func createLinkToken() async throws -> String { "" }
    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO { fatalError() }
    func listAchRelationships() async throws -> [AchRelationshipDTO] { [] }
    func deleteAchRelationship(id: UUID) async throws {}
    func createReauthLinkToken(relationshipId: UUID) async throws -> String { "" }
    func completeReauth(relationshipId: UUID) async throws {}
    func createTransfer(
        relationshipId: String,
        amount: Decimal,
        direction: TransferDirection
    ) async throws -> TransferResponse { fatalError() }
    func listTransfers() async throws -> [TransferResponse] { [] }
    func listDividends(limit: Int, offset: Int) async throws -> [DividendResponse] { [] }
}

private func previewView(_ service: PreviewFundingService) -> some View {
    NavigationStack {
        CashEnrollmentStatusView(viewModel: CashEnrollmentStatusViewModel(service: service))
    }
}

#Preview("Active") {
    previewView(PreviewFundingService(state: .active))
        .preferredColorScheme(.dark)
}

#Preview("Pending") {
    previewView(PreviewFundingService(state: .pending))
        .preferredColorScheme(.dark)
}

#Preview("Not enrolled") {
    previewView(PreviewFundingService(state: .notEnrolled))
        .preferredColorScheme(.dark)
}

#Preview("Not enrolled (light)") {
    previewView(PreviewFundingService(state: .notEnrolled))
        .preferredColorScheme(.light)
}

#Preview("Unavailable") {
    previewView(PreviewFundingService(state: .unavailable))
        .preferredColorScheme(.dark)
}
#endif
