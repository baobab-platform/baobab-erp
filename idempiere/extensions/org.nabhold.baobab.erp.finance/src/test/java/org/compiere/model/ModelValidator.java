package org.compiere.model;

/** Synthetic test-only mirror of selected upstream timing names/overlaps. */
public interface ModelValidator {
    int TYPE_BEFORE_NEW = 1;
    int TYPE_AFTER_NEW = 4;
    int TYPE_BEFORE_CHANGE = 2;
    int TYPE_AFTER_CHANGE = 5;
    int TIMING_BEFORE_PREPARE = 1; // deliberately overlaps TYPE_BEFORE_NEW
    int TIMING_BEFORE_COMPLETE = 9;
    int TIMING_AFTER_PREPARE = 4;  // deliberately overlaps TYPE_AFTER_NEW
    int TIMING_AFTER_COMPLETE = 10;
}
