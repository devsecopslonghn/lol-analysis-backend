@Library(['company-ci', 'company-cd']) _

ciPipeline(
    type: 'container',
    application: 'lol-analysis-backend',
    language: 'python',
    buildSystem: 'container',
    sourceDirectories: ['.'],
    sonarSources: ['src'],
    securityScans: [
        sonar: false,
        trivy: true,
        codeql: false,
        securityBlock: false
    ],
    artifactProfile: 'nexus-container-dev',
    images: [[name: 'backend', dockerfile: 'Dockerfile']],
    publishPolicy: [primaryOnly: true, primaryBranch: 'master'],
    generatedGitOps: [
        commitPattern: /^chore\(gitops\): deploy .* \[skip ci\]$/,
        files: ['values.yaml']
    ]
)

withEnv([
    'CD_GITOPS_REPOSITORY=https://github.com/devsecopslonghn/lol-analysis-helm-chart.git',
    'CD_GITOPS_BRANCH=master',
    'CD_GITOPS_PROFILE=lol-analysis-gitops'
]) {
    cdPipeline(
        strategy: 'gitops',
        application: 'lol-analysis-backend',
        deploymentProfile: 'lol-analysis-dev',
        gitopsRepository: 'configured',
        valuesFile: 'values.yaml',
        imageTagPath: 'image.backend.tag',
        generatedGitOps: [
            commitPattern: /^chore\(gitops\): deploy .* \[skip ci\]$/,
            files: ['values.yaml']
        ],
        variables: [imageTag: env.IMAGE_TAG]
    )
}
