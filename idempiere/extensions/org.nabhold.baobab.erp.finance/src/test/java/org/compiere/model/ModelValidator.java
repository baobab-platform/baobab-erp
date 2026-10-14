package org.compiere.model;

/** Synthetic test-only mirror of selected upstream timing names/overlaps and topic arrays. */
public interface ModelValidator {
    int TYPE_BEFORE_NEW = 1;
    int TYPE_AFTER_NEW = 4;
    int TYPE_BEFORE_CHANGE = 2;
    int TYPE_AFTER_CHANGE = 5;
    int TIMING_BEFORE_PREPARE = 1; // deliberately overlaps TYPE_BEFORE_NEW
    int TIMING_BEFORE_COMPLETE = 9;
    int TIMING_AFTER_PREPARE = 4;  // deliberately overlaps TYPE_AFTER_NEW
    int TIMING_AFTER_COMPLETE = 10;

    // Indexed by the constants above, as upstream correlates topics and timings.
    // Index 3 / 2,3,5-8 carry topics with no constant here: unknown timings fail closed.
    String[] tableEventTopics = {
        "", "adempiere/po/beforeNew", "adempiere/po/beforeChange", "adempiere/po/beforeDelete",
        "adempiere/po/afterNew", "adempiere/po/afterChange"};
    String[] documentEventTopics = {
        "", "adempiere/doc/beforePrepare", "adempiere/doc/beforeVoid", "adempiere/doc/beforeClose",
        "adempiere/doc/afterPrepare", "adempiere/doc/beforeReverseCorrect", null, "",
        "adempiere/doc/beforePost", "adempiere/doc/beforeComplete", "adempiere/doc/afterComplete"};
}
