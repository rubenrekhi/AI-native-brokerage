import Foundation
@testable import Sevino

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {
    var lastPath: String?
    var lastMethod: String?
    var lastQuery: [String: String]?
    var lastBody: (any Encodable)?
    var responseToReturn: Any?
    var errorToThrow: Error?

    private func castResponse<T: Decodable>() throws -> T {
        guard let response = responseToReturn as? T else {
            throw URLError(.badServerResponse)
        }
        return response
    }

    func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T {
        lastPath = path
        lastMethod = "GET"
        lastQuery = query
        if let error = errorToThrow { throw error }
        return try castResponse()
    }

    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "POST"
        lastBody = body
        if let error = errorToThrow { throw error }
        return try castResponse()
    }

    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "PUT"
        lastBody = body
        if let error = errorToThrow { throw error }
        return try castResponse()
    }

    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "PATCH"
        lastBody = body
        if let error = errorToThrow { throw error }
        return try castResponse()
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        lastPath = path
        lastMethod = "DELETE"
        if let error = errorToThrow { throw error }
        return try castResponse()
    }
}
