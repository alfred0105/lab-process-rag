export type Variable={id:number;name:string;value:string;unit?:string|null;material?:string|null;source_type:string};
export type Step={id:number;name:string;step_type:string;order_index:number;description:string;variables:Variable[]};
export type Experiment={id:number;code:string;name:string;target:string;status:string;demo:boolean;steps:Step[];results:{key:string;value:string;unit?:string|null}[];observations:{category:string;description:string}[]};
export type Evidence={evidence_id:number;paper_title:string;page:number;section?:string|null;text:string;relevance_score:number;source_type:string};
