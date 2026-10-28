/*
 * Copyright 2017 the original author or authors.
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

package org.gradle.performance.regression.buildcache

import org.gradle.performance.annotations.RunFor
import org.gradle.performance.annotations.Scenario
import org.gradle.performance.fixture.CrossVersionPerformanceTestRunner
import org.gradle.performance.fixture.JavaTestProject
import org.gradle.performance.mutator.RetryingClearGradleUserHomeMutator
import org.gradle.profiler.BuildContext
import org.gradle.profiler.BuildMutator
import org.gradle.profiler.InvocationSettings
import org.gradle.profiler.Phase
import org.gradle.profiler.mutations.AbstractScheduledMutator
import org.gradle.profiler.mutations.ApplyAbiChangeToJavaSourceFileMutator
import org.gradle.profiler.mutations.ApplyNonAbiChangeToJavaSourceFileMutator
import org.gradle.profiler.mutations.ClearProjectCacheMutator
import org.gradle.test.fixtures.keystore.TestKeyStore

import java.nio.charset.StandardCharsets
import java.security.MessageDigest

import static org.gradle.performance.annotations.ScenarioType.PER_COMMIT
import static org.gradle.performance.annotations.ScenarioType.PER_DAY
import static org.gradle.performance.results.OperatingSystem.LINUX

@RunFor(
    @Scenario(type = PER_DAY, operatingSystems = [LINUX], testProjects = ["largeJavaMultiProject", "largeMonolithicJavaProject"])
)
class TaskOutputCachingJavaPerformanceTest extends AbstractTaskOutputCachingPerformanceTest {

    def setup() {
        runner.warmUpRuns = 11
        runner.runs = 21
        runner.minimumBaseVersion = "3.5"
    }

    def "clean assemble with remote http cache"() {
        setupTestProject(runner)
        protocol = "http"
        pushToRemote = true
        runner.useDaemon = false
        runner.warmUpRuns = 2
        runner.runs = 8
        runner.addBuildMutator { cleanLocalCache() }

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    @RunFor(
        @Scenario(type = PER_DAY, operatingSystems = [LINUX], testProjects = ["smallJavaMultiProjectManyExternalDependencies"])
    )
    /*
     * Similar to the "first use" scenario, because ephemeral agents have no local caches, but we do have a well-populated remote
     * cache. This scenario measures how much overhead Gradle's startup and input fingerprinting add on top of the cache hits.
     */
    def "clean check on ephemeral ci with remote http cache"() {
        runner.cleanTasks = ["clean"]
        runner.tasksToRun = ["check"]
        protocol = "http"
        pushToRemote = true
        runner.useDaemon = false
        runner.warmUpRuns = 1
        runner.runs = 3
        runner.addBuildMutator { invocationSettings ->
            new RetryingClearGradleUserHomeMutator(invocationSettings.gradleUserHome, AbstractScheduledMutator.Schedule.BUILD)
        }
        runner.addBuildMutator { invocationSettings ->
            new ClearProjectCacheMutator(invocationSettings.projectDir, AbstractScheduledMutator.Schedule.BUILD)
        }

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    def "clean assemble with remote https cache"() {
        setupTestProject(runner)
        protocol = "https"
        pushToRemote = true
        runner.useDaemon = false
        runner.warmUpRuns = 2
        runner.runs = 8
        runner.addBuildMutator { cleanLocalCache() }

        def keyStore = TestKeyStore.init(temporaryFolder.file('ssl-keystore'))
        keyStore.enableSslWithServerCert(buildCacheServer)

        runner.gradleOpts.addAll(keyStore.serverAndClientCertArgs)

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    def "clean assemble with empty local cache"() {
        given:
        setupTestProject(runner)
        runner.warmUpRuns = 2
        runner.runs = 8
        pushToRemote = false
        runner.useDaemon = false
        runner.addBuildMutator { cleanLocalCache() }

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    def "clean assemble with empty remote http cache"() {
        given:
        setupTestProject(runner)
        runner.warmUpRuns = 2
        runner.runs = 8
        pushToRemote = true
        runner.useDaemon = false
        runner.addBuildMutator { cleanLocalCache() }
        runner.addBuildMutator { cleanRemoteCache() }

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    @RunFor(
        @Scenario(type = PER_COMMIT, operatingSystems = [LINUX], testProjects = ["largeJavaMultiProject", "largeMonolithicJavaProject"])
    )
    def "clean assemble with local cache"() {
        given:
        setupTestProject(runner)
        runner.args += "--parallel"
        pushToRemote = false

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    @RunFor(
        @Scenario(type = PER_DAY, operatingSystems = [LINUX], testProjects = ["largeMonolithicJavaProject"])
    )
    def "clean assemble with local cache and cold project cache"() {
        given:
        setupTestProject(runner)
        runner.minimumBaseVersion = "7.2"
        runner.useDaemon = false
        runner.args += ["--no-watch-fs", "--console=plain"]
        runner.warmUpRuns = 3
        runner.runs = 10
        pushToRemote = false
        runner.addInterceptor { builder ->
            builder.invocation {
                buildLog(new File(workingDirectory, "build.log"))
            }
        }
        runner.addBuildMutator { invocationSettings ->
            new ClearProjectCacheMutator(invocationSettings.projectDir, AbstractScheduledMutator.Schedule.BUILD)
        }
        runner.addBuildMutator { invocationSettings ->
            new BuildMutator() {
                @Override
                void beforeBuild(BuildContext context) {
                    invocationSettings.buildLog.text = ""
                    if (context.phase == Phase.WARM_UP && context.iteration == 1) {
                        recordSourceInventory(invocationSettings)
                    }
                }

                @Override
                void afterBuild(BuildContext context, Throwable error) {
                    def trace = new File(invocationSettings.outputDir, "build-${context.phase}-${context.iteration}.log")
                    trace.parentFile.mkdirs()
                    trace.bytes = invocationSettings.buildLog.bytes
                    if (error == null && context.phase == Phase.MEASURE) {
                        assert trace.readLines().contains("> Task :compileJava FROM-CACHE")
                    }
                }
            }
        }

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    @RunFor([
        @Scenario(type = PER_COMMIT, operatingSystems = [LINUX], testProjects = ["largeJavaMultiProject"],
            comment = "We only test the multi-project here since for the monolithic project we would have no cache hits. This would mean we actually would test incremental compilation."
        )
    ])
    def "clean assemble for abi change with local cache"() {
        given:
        setupTestProject(runner)
        def testProject = JavaTestProject.projectFor(runner.testProject)
        runner.addBuildMutator { new ApplyAbiChangeToJavaSourceFileMutator(new File(it.projectDir, testProject.config.fileToChangeByScenario['assemble'])) }
        runner.args += "--parallel"
        pushToRemote = false

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    @RunFor([
        @Scenario(type = PER_COMMIT, operatingSystems = [LINUX], testProjects = ["largeJavaMultiProject"],
            comment = "We only test the multi-project here since for the monolithic project we would have no cache hits. This would mean we actually would test incremental compilation."
        )
    ])
    def "clean assemble for non-abi change with local cache"() {
        given:
        setupTestProject(runner)
        def testProject = JavaTestProject.projectFor(runner.testProject)
        runner.addBuildMutator { new ApplyNonAbiChangeToJavaSourceFileMutator(new File(it.projectDir, testProject.config.fileToChangeByScenario['assemble'])) }
        runner.args += "--parallel"
        pushToRemote = false

        when:
        def result = runner.run()

        then:
        result.assertCurrentVersionHasNotRegressed()
    }

    private static void recordSourceInventory(InvocationSettings settings) {
        def root = new File(settings.projectDir, "src/main/java")
        List<File> sources = []
        root.eachFileRecurse { file ->
            if (file.isFile() && file.name.endsWith(".java")) {
                sources.add(file)
            }
        }
        sources.sort { it.path }
        int expected = Integer.parseInt(System.getenv("NORMALIZED_CACHE_SOURCE_FILES") ?: "50000")
        assert sources.size() == expected
        def digest = MessageDigest.getInstance("SHA-256")
        long bytes = 0
        sources.each { source ->
            def relative = root.toPath().relativize(source.toPath()).toString()
            digest.update(relative.getBytes(StandardCharsets.UTF_8))
            digest.update((byte) 0)
            def content = source.bytes
            bytes += content.length
            digest.update(content)
            digest.update((byte) 0)
        }
        def sha256 = digest.digest().encodeHex().toString()
        new File(settings.outputDir, "source-inventory.json").text =
            """{"files":${sources.size()},"bytes":${bytes},"sha256":"${sha256}"}\n"""
    }

    static def setupTestProject(CrossVersionPerformanceTestRunner runner) {
        runner.tasksToRun = ["assemble"]
        runner.cleanTasks = ["clean"]
    }
}
