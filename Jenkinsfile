// Orchestration only. Every stage calls a repository entrypoint, in the same order as
// the GitHub Actions workflow and the GitLab pipeline, so the three definitions cannot
// drift apart. Shell steps use single quotes so nothing is interpolated by Groovy.

pipeline {
    agent any

    options {
        timeout(time: 75, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    stages {
        stage('Bootstrap') {
            steps {
                sh './scripts/bootstrap.sh'
            }
        }

        stage('Tooling') {
            steps {
                sh './scripts/terra.sh doctor'
            }
        }

        stage('Repository validation') {
            steps {
                sh './scripts/terra.sh validate'
                sh './scripts/terra.sh traceability'
            }
        }

        stage('Unit') {
            steps {
                sh './scripts/terra.sh test unit'
            }
        }

        // Static contract checks run before the environment exists.
        stage('Static contract') {
            steps {
                sh './scripts/terra.sh test contract --mode static'
            }
        }

        stage('Security') {
            steps {
                sh './scripts/terra.sh test security'
            }
        }

        stage('Pipeline contract') {
            steps {
                sh './scripts/terra.sh test pipeline'
            }
        }

        stage('Environment') {
            steps {
                sh './scripts/terra.sh up'
                sh './scripts/terra.sh status'
            }
        }

        stage('Integration') {
            steps {
                sh './scripts/terra.sh test integration'
            }
        }

        stage('Formal procedures') {
            steps {
                sh './scripts/terra.sh procedure run TP-ING-002'
                sh './scripts/terra.sh procedure run TP-API-004'
                sh './scripts/terra.sh procedure run TP-SYS-001'
            }
        }

        // The Postman phase runs against the started system.
        stage('Running contract') {
            steps {
                sh './scripts/terra.sh test contract --mode postman'
            }
        }

        stage('Performance') {
            steps {
                sh './scripts/terra.sh test performance'
            }
        }

        stage('Resilience') {
            steps {
                sh './scripts/terra.sh procedure run TP-RES-003'
                sh './scripts/terra.sh test resilience'
            }
        }

        stage('Evidence') {
            steps {
                sh './scripts/terra.sh procedure run TP-EVD-005'
                sh './scripts/terra.sh evidence'
            }
        }
    }

    post {
        always {
            sh './scripts/terra.sh diagnostics'
            archiveArtifacts artifacts: 'artifacts/**', allowEmptyArchive: false, fingerprint: true
            junit allowEmptyResults: false, testResults: 'artifacts/junit/*.xml'
            sh './scripts/terra.sh down'
        }
    }
}
