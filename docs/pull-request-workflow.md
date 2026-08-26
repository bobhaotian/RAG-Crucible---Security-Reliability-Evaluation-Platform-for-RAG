# Pull request workflow

Changes must reach `main` through a reviewed pull request:

1. Create a feature branch from the latest `main`.
2. Commit and push the change to that branch.
3. Open a pull request targeting `main`.
4. Wait for the Python, dashboard, and Docker checks to pass.
5. Obtain one approval from someone other than the pull-request author.
6. Merge the pull request.

If additional commits are pushed after approval, the previous approval is
dismissed and the updated change must be reviewed again.
