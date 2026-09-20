**Content of this document**

[[_TOC_]]

# Contribution Guide
This guide will give some hints if you want to contribute to CIVITAS/CORE.

## Introduction
Thank you for considering contributing to our project! It's people like you that make CIVITAS/CORE great. This document outlines the guidelines and expectations for contributing to our project, ensuring high quality standards and a positive collaborative environment.

### What are these guidelines for?
These guidelines serve as a reference for contributors, both new and experienced, to understand the expectations and processes involved in contributing to our project. By following these guidelines, we all can pay respect to the time of the maintainers and contributers managing this project and helping you assessing changes and finalize your merge requests.

### What contributions are we looking for?
CIVITAS/CORE is a project that welcomes all kinds of contributions from the community. We welcome various contributions, including bug fixes, feature enhancements, documentation improvements, feature requests, and community engagement.

While we value all contributions, there are certain types that may not align with the project's goals or development philosophy. Before making a contribution, please ensure it fits within the project's scope.

Please, don't use the issue tracker for support questions. Instead, check our communication channels to reach out for help. Also, Stack Overflow is worth considering.


## Ground Rules
### Code of conduct
Every contributor, regardless of the type of contribution, is asked to adhere to the code of conduct.

Like many other open source projects, we apply the Contributor Covenant as our Code of Conduct, which is available [in english](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) and [in german](https://www.contributor-covenant.org/de/version/2/1/code_of_conduct/).

Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the community leaders responsible for enforcement at [core@civitasconnect.digital](mailto:core@civitasconnect.digital). As a result, indivuduals might be excluded and banned from the community.

### Additional responsibilites
By contributing code, you agree to fulfill certain technical responsibilities:

- Ensure vendor- and operator-independence for every change that is accepted. Especially, don't create dependencies to proprietary, non-open source software.
- Create issues for any major changes and enhancements that you wish to make. Discuss things transparently and get community feedback.
- Keep feature versions as small as possible, preferably one new feature per version.
- When contributing code, make sure to adhere to our coding standards.
- Respect the intellectual property rights of others and other projects and adhere to the conditions of the software license, which you find at the end of the README file of all our projects.
- Be welcoming to newcomers and encourage diverse new contributors from all backgrounds. See the [Python Community Code of Conduct](https://www.python.org/psf/conduct/).


## Project Structure
* The project is divided into [the core platform](https://gitlab.com/civitas-connect/civitas-core/civitas-core-v2/civitas-core-platform), [the documentation](https://gitlab.com/civitas-connect/civitas.core/documentation), the [the deployment](https://gitlab.com/civitas-connect/civitas-core/civitas-core-v2/civitas-core-deployment) and various other repositories that are used by the platform repository.
* The **core platform** repository contains everything needed to set up the platform.
* Within the **documentation** repository you can find extensive documentation about deployment, administration and usage of the platform.

### Naming Conventions
* All names (groups and projects) are lowercase and delimited by a hyphen (e.g. group-or-project-name).
* The project's/group's name **MUST** refer to the project's/group's slug! (Avoid "Umlaute" and special characters, e.g. "ä"->"ae").
* Prefer rather explicit and longer project/subgroup names that provide good understanding of the project's objectives.
* avoid vendor names like "PAX...", "Osram..." - keep the name vendor-independent.
* avoid city names like "BTXL..." - keep the name city-independent.

## Your First Contribution

If you're new to open source or this project, we recommend starting with a beginner-friendly task. To learn about making a contribution, visit websites like [makeapullrequest.com](http://makeapullrequest.com/) and [firsttimersonly.com](http://www.firsttimersonly.com/), which curate examples.

### Getting Started

To submit a contribution, follow these steps:

1. Fork the repository to your own Gitlab account.
2. Create a new branch for your changes.
3. Make the necessary changes and commit them.
4. Push your branch to your forked repository.
5. Open a merge request with a descriptive title and detailed explanation of your changes.

If your contribution requires tests, make sure to include them in your merge request. Provide instructions on how to run the tests, if applicable.


### Git Commit Messages

- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters or less
- Reference issues and merge requests liberally after the first line
- When only changing documentation, include [ci skip] in the commit title

### Documentation

- For new or changed features adjust the documentation files in the documentation repository
- Document changes in the changelog
- If user need to perform additional steps before upgrading to a version containing your changes describe these in the migration guides

#### Using Diagrams for Documentation

* Please use [draw.io](http://diagrams.net) as tool. If you use VSCode, [this plugin](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio) lets you edit and export diagrams inside VSCode.
* Draw.io diagrams can be exported as images that include the source. Make sure you always create a "combined" export as `*.drawio.png` in a single file and include it into the markdown documentation.



### How to Report a Bug

We provide a lightweight way to report unexpected behaviour or bugs when testing the platform. Open the [Findings Board](https://gitlab.com/groups/civitas-connect/civitas-core/-/boards/11418946?types=1235) and check if your finding already exists. If not, create a new finding [here](https://gitlab.com/civitas-connect/civitas-core/civitas-core-v2/civitas-core-platform/-/work_items/new). Choose Type "Finding", add a short title and a description with observed and expected behaviour. We will check new Findings regularly.

> If you discover a security vulnerability, **do not** open an issue. Instead, please email us at [core@civitasconnect.digital](mailto:core@civitasconnect.digital) directly, so we can address it promptly and confidentially.

### How to Suggest a Feature or Enhancement

We encourage suggestions for new features or enhancements that align with the project's roadmap, goals, and development philosophy. Before submitting a suggestion, please review our existing documentation and discussions to ensure it hasn't been proposed before. If it's a novel idea, feel free to suggest it through the appropriate channels, providing clear and concise information about the feature's purpose and potential benefits. The most transparent way is to create an issue in this repository and add the label `type::feature_request` to it. The project management will communicate decisions regarding this feature request in this ticket and create issues for the implementation that are linked to it.

### Code Review Process

Code reviews are an essential part of maintaining code quality and consistency. Our project follows a peer review process, where designated reviewers provide feedback on submitted merge requests. Once a merge request is approved, one of the project maintainers will merge it. Contributors can expect to receive feedback within a reasonable timeframe, and communication regarding the progress of their contributions will be conducted through the merge request comments.

To ensure smooth collaboration, contributors are not granted direct commit access. However, exceptional contributors who consistently provide valuable contributions may be.

## Release Process
CIVITAS/CORE follows the conventions of [Semantic Versioning](https://semver.org). Breaking changes result in an increased major version, new features increment the minor version and bugfixes and patches increase the patch version. Versions should be as atomic as possible. If you want to publish a new version follow this process:
1. Develop features and bugfixes in feature branches
2. If you want to merge a branch create a merge request to merge into the `main` branch and follow its [review process](https://gitlab.com/civitas-connect/civitas-core/civitas-core/-/blob/main/CONTRIBUTION-GUIDE.md#code-review-process)
3. If all code you need for a new version is on the `main` branch make sure no new bugs were introduced to the code base
4. Append to the top of the CHANGELOG.md what changed feature-wise since the last version and what are known issues
5. If manual steps need to be performed to upgrade to the new version document them in the MIGRATION.md
6. Create a gitlab release with a corresponding git tab following the following name schema: `v<major>.<minor>.<patch>`

If older (major or minor) versions need to be patched create a branch from the correspondig git tag and merge the patches into this branch. Then follow the above steps to create a patched version without merging the changes to the `main` branch.

## How to apply the license
All contributions to this repository are licensed under the [EU PL 1.2](LICENSE) or any later version.
This project doesn't require a CLA (Contributor License Agreement). The copyright belongs to all the individual contributors.

Information on how the license header should be set can be found in the [documentation](https://docs.core.civitasconnect.digital/docs_v2/Development/intro).

Please add this header if it does not exist and add your name, if you changed the file substantially.

> NB! If a file is already licensed under a different license, that license is not to be changed.
