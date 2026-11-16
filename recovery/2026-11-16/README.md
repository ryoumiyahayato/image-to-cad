# Recovered Git bundles — 2026-11-16

**Status: partial recovery archive, NOT a complete source synchronization.**

These are byte-preserved Git bundles recovered from the owner's connected cloud archive. The listed heads were read from the actual bundle files with `git bundle list-heads`; local file digests were computed with SHA-256. They are stored as GitHub blobs and are not imported as GitHub branch commits.

| File | Git bundle head | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| [online-r2.bundle](git-bundles/online-r2.bundle) | `81e07890852f6785430f88672a40964c76101f0e` | 7568 | `118c94ffdde35da62614f4768fc549081e3693de182f1088db3fa000860fc3c0` |
| [online-r3.bundle](git-bundles/online-r3.bundle) | `952c1aa01b466170eae4d3a9173f34a7eb742fdf` | 8166 | `d808beed23cfb1305fe1327a00f3a8de133e73ea5f8e06b5129cbbe43bc1bc96` |
| [online-r4.bundle](git-bundles/online-r4.bundle) | `8e5512f6419b540d7734f91ed08da84977caf1ee` | 8258 | `ebbd2a4d75f8bcfe4f8531bf3543639e61452205b93dd54226f8fada52aefb72` |
| [online-r5.bundle](git-bundles/online-r5.bundle) | `79152b4edd4157683bb10462d026f731873ca97f` | 3487 | `5a6d644d87d95427fc74ef2180d76a44429981ac27d53fd9890a95cd36abd413` |
| [online-r6.bundle](git-bundles/online-r6.bundle) | `68639513277ec3883d561867beb110625d49cabe` | 8074 | `7a858b43b2e566ae8e5700f4fa47bc35200155cd65bf46aa02b69cb4b27ffd32` |
| [online-r7.bundle](git-bundles/online-r7.bundle) | `e628e81b245b7ed472f15c44d4eaaaca20ef0eb1` | 8534 | `915a6490b060b857e687075e6302f2908a59d18df0b5397153639b06d1d33975` |
| [online-r8.bundle](git-bundles/online-r8.bundle) | `e351ddceedec4ff664469633f09aaaf258456a65` | 5326 | `1913564c7c9cca0c51f46f7efa17971c96c9aa2dfe906259658d65f674838cba` |
| [online-r9.bundle](git-bundles/online-r9.bundle) | `129c1352c7b5edd21977247fcdd6298bfdc5a9ad` | 7223 | `ff55dc6e50669cfbea055aab137baecc1999205c067a585991ba47b022554676` |
| [online-r12-save-handoff.bundle](git-bundles/online-r12-save-handoff.bundle) | `92b71cf62902668f14d56b1d8447782a672e7962` | 7570 | `41b6b38d0315959ecce844f07ec3da293e9cfe7c3da43450680ac951147ff589` |

### Missing prerequisites

- The base commit for online-r2, `c8f31bbaa4ebbf9c41256b6d302d21e67b8b3ec0`, is not present in the GitHub repository as of this recovery.
- A separate 2026-11-13 source workset exists in the owner's private archive; its three ZIP parts reconstruct to 239,528,356 bytes (SHA-256 `f3e3aaac88442b26c686c97065a830f6d8b563d71031339d2c7549098ae2d9f8`). It is not part of this GitHub commit.
- The r10 and r11 source ancestry is incomplete in this archive. The r11 local acceptance ZIP was located and its internal bundle head was verified as `0255b355e2378d6050bf7e4498d0e39d92c47cfa`, but that bundle has not been copied to this repository.
- The r12 bundle requires r11 commit `0255b355e2378d6050bf7e4498d0e39d92c47cfa`; therefore `git bundle verify` cannot complete without recovering the prerequisite history.

These files are recovery artifacts, not evidence that the original Git commits were pushed. Do not use them to update `main` until all prerequisites are recovered and compared.