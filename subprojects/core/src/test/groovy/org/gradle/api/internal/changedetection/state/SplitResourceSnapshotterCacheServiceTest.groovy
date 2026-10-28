/*
 * Copyright 2026 Gradle and contributors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.gradle.api.internal.changedetection.state

import org.gradle.cache.GlobalCacheLocations
import org.gradle.internal.file.FileMetadata
import org.gradle.internal.file.impl.DefaultFileMetadata
import org.gradle.internal.fingerprint.hashing.FileSystemLocationSnapshotHasher
import org.gradle.internal.fingerprint.hashing.RegularFileSnapshotContextHasher
import org.gradle.internal.hash.TestHashCodes
import org.gradle.internal.serialize.HashCodeSerializer
import org.gradle.internal.snapshot.RegularFileSnapshot
import org.gradle.testfixtures.internal.TestInMemoryIndexedCache
import spock.lang.Specification

class SplitResourceSnapshotterCacheServiceTest extends Specification {
    def globalCache = newCache()
    def globalCacheLocations = Stub(GlobalCacheLocations)
    def firstBuildCache = new SplitResourceSnapshotterCacheService(globalCache, newCache(), globalCacheLocations)
    def secondBuildCache = new SplitResourceSnapshotterCacheService(globalCache, newCache(), globalCacheLocations)
    def configurationHash = TestHashCodes.hashCodeFrom(1)

    def "reuses normalized hashes across build trees and source locations"() {
        def hasher = Mock(FileSystemLocationSnapshotHasher)
        def firstSnapshot = snapshot("first/src/Foo.java", 2)
        def secondSnapshot = snapshot("second/src/Foo.java", 2)

        when:
        def firstHash = firstBuildCache.hashFile(firstSnapshot, hasher, configurationHash)

        then:
        firstHash == normalizedHash
        1 * hasher.hash(firstSnapshot) >> normalizedHash

        when:
        def secondHash = secondBuildCache.hashFile(secondSnapshot, hasher, configurationHash)

        then:
        secondHash == normalizedHash
        0 * hasher._

        where:
        normalizedHash << [TestHashCodes.hashCodeFrom(3), null]
    }

    def "recomputes normalized hashes when content or normalizer configuration changes"() {
        def hasher = Mock(FileSystemLocationSnapshotHasher)
        def firstSnapshot = snapshot("first/src/Foo.java", 2)
        def secondSnapshot = snapshot("second/src/Foo.java", secondContentHash)
        def firstNormalizedHash = TestHashCodes.hashCodeFrom(3)
        def secondNormalizedHash = TestHashCodes.hashCodeFrom(4)

        when:
        def firstHash = firstBuildCache.hashFile(firstSnapshot, hasher, configurationHash)
        def secondHash = secondBuildCache.hashFile(secondSnapshot, hasher, TestHashCodes.hashCodeFrom(secondConfigurationHash))

        then:
        firstHash == firstNormalizedHash
        secondHash == secondNormalizedHash
        1 * hasher.hash(firstSnapshot) >> firstNormalizedHash
        1 * hasher.hash(secondSnapshot) >> secondNormalizedHash

        where:
        secondContentHash | secondConfigurationHash
        5                 | 1
        2                 | 6
    }

    def "does not cache failed normalization"() {
        def hasher = Mock(FileSystemLocationSnapshotHasher)
        def firstSnapshot = snapshot("first/src/Foo.java", 2)
        def secondSnapshot = snapshot("second/src/Foo.java", 2)
        def normalizedHash = TestHashCodes.hashCodeFrom(3)

        when:
        firstBuildCache.hashFile(firstSnapshot, hasher, configurationHash)

        then:
        1 * hasher.hash(firstSnapshot) >> { throw new IOException("Cannot normalize source") }
        thrown(IOException)

        when:
        def actualHash = secondBuildCache.hashFile(secondSnapshot, hasher, configurationHash)

        then:
        actualHash == normalizedHash
        1 * hasher.hash(secondSnapshot) >> normalizedHash
    }

    def "preserves classpath resource cache scope for global location #globalLocation"() {
        def locations = Stub(GlobalCacheLocations) {
            isInsideGlobalCache(_) >> globalLocation
        }
        def firstCache = new SplitResourceSnapshotterCacheService(globalCache, newCache(), locations)
        def secondCache = new SplitResourceSnapshotterCacheService(globalCache, newCache(), locations)
        def hasher = Mock(RegularFileSnapshotContextHasher)
        def firstContext = new DefaultRegularFileSnapshotContext({ ["Foo.class"] as String[] }, snapshot("first/Foo.class", 2))
        def secondContext = new DefaultRegularFileSnapshotContext({ ["Foo.class"] as String[] }, snapshot("second/Foo.class", 2))
        def normalizedHash = TestHashCodes.hashCodeFrom(3)

        when:
        def firstHash = firstCache.hashFile(firstContext, hasher, configurationHash)
        def secondHash = secondCache.hashFile(secondContext, hasher, configurationHash)

        then:
        firstHash == normalizedHash
        secondHash == normalizedHash
        expectedCalls * hasher.hash(_) >> normalizedHash

        where:
        globalLocation | expectedCalls
        true           | 1
        false          | 2
    }

    private static DefaultResourceSnapshotterCacheService newCache() {
        return new DefaultResourceSnapshotterCacheService(new TestInMemoryIndexedCache(new HashCodeSerializer()))
    }

    private static RegularFileSnapshot snapshot(String path, int contentHash) {
        return new RegularFileSnapshot(path, new File(path).name, TestHashCodes.hashCodeFrom(contentHash), DefaultFileMetadata.file(100, 10, FileMetadata.AccessType.DIRECT))
    }
}
