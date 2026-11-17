# Q8231 capture/Registry lock order review

Status: the proposed ABBA path is refuted for the actual source. This is not a runtime schedulability or deadlock-freedom proof.

Pinned source: Q8231d8b9d67e5188787b69225a72145f2d4c5a63, process_lifecycle.py SHA 93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65.

The actual Registry.launch (line 702) and Registry.run (804) are not decorated by _synchronized and do not hold self._mutex across the launch operation. launch acquires the shared capture flock at line 726, then _append takes self._mutex and the journal flock at lines 642-651. The observer takes the same shared capture lock before native/listener helper launch; nested capture_lock is explicitly reentrant only within that same thread. Both paths therefore use capture -> Registry mutex -> journal flock.

The two decorated methods are remember and close. remember holds the Registry mutex while independently parsing saved native evidence and appending journal events; neither it nor close acquires the shared capture lock. _state/sample use the Registry mutex and actual journal reads, without acquiring the shared capture lock. No checked source path was found that holds the journal flock while requesting the shared capture lock.

Do not add Registry._mutex -> shared capture flock around the new owned guard mode while retaining the actual legacy launch path: this would introduce the reverse order and create the very hazard under review. No guard/lifecycle change is recommended on the refuted premise. If a future Registry implementation changes launch's outer synchronization, it must be re-audited together with the observer.

Bounded controls use actual Registry.launch/_append/capture_lock implementations with a project-local synthetic command file and journal, real thread RLocks and real native flock. Popen is replaced by an immediate controlled exception: no process, native collector, API or model starts. Every thread has a release path and bounded join. These controls confirm the checked order and a finite adversarial schedule; they do not prove all schedules.
