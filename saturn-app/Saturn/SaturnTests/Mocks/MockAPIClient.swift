import Foundation
@testable import Saturn

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {
    var lastPath: String?
    var lastMethod: String?
    var lastBody: (any Encodable)?
    var responseToReturn: Any?
    var errorToThrow: Error?

    func get<T: Decodable>(_ path: String) async throws -> T {
        lastPath = path
        lastMethod = "GET"
        if let error = errorToThrow { throw error }
        return responseToReturn as! T
    }

    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "POST"
        lastBody = body
        if let error = errorToThrow { throw error }
        return responseToReturn as! T
    }

    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "PUT"
        lastBody = body
        if let error = errorToThrow { throw error }
        return responseToReturn as! T
    }

    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        lastPath = path
        lastMethod = "PATCH"
        lastBody = body
        if let error = errorToThrow { throw error }
        return responseToReturn as! T
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        lastPath = path
        lastMethod = "DELETE"
        if let error = errorToThrow { throw error }
        return responseToReturn as! T
    }
}
